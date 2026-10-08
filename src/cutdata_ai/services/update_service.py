"""Check the project's public GitHub releases for a newer installer."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config.constants import APP_VERSION, REPOSITORY_URL

_REPOSITORY_PATH = REPOSITORY_URL.rstrip("/").split("github.com/", 1)[-1]
LATEST_RELEASE_API = f"https://api.github.com/repos/{_REPOSITORY_PATH}/releases/latest"
# Only an installer published on this project's own releases is ever run.
_DOWNLOAD_PREFIX = f"https://github.com/{_REPOSITORY_PATH}/releases/download/".casefold()
_INSTALLER_NAME = re.compile(r"^CutData-AI-Setup-[0-9][0-9A-Za-z.\-]*\.exe$")
_USER_AGENT = f"CutData-AI/{APP_VERSION} (update check)"
_TIMEOUT_SECONDS = 15


class UpdateError(RuntimeError):
    """The update check or download could not be completed."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    notes: str
    page_url: str
    installer_url: str = ""
    installer_name: str = ""
    installer_size: int = 0
    sha256: str = ""

    @property
    def has_installer(self) -> bool:
        return bool(self.installer_url)


def parse_version(text: object) -> tuple[int, ...]:
    """'v0.2.10' -> (0, 2, 10); anything unreadable sorts lowest."""

    numbers = re.findall(r"\d+", str(text or "").split("-", 1)[0].split("+", 1)[0])
    return tuple(int(number) for number in numbers[:4])


def is_newer(candidate: object, current: object = APP_VERSION) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    if not new:
        return False
    width = max(len(new), len(old))
    return new + (0,) * (width - len(new)) > old + (0,) * (width - len(old))


def release_from_payload(payload: Any) -> UpdateInfo | None:
    """Read a GitHub release object; drafts and pre-releases are ignored."""

    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        return None
    version = str(payload.get("tag_name") or "").strip().lstrip("vV")
    if not parse_version(version):
        return None
    page_url = str(payload.get("html_url") or "")
    if not page_url.casefold().startswith(REPOSITORY_URL.casefold()):
        page_url = f"{REPOSITORY_URL}/releases"
    info = UpdateInfo(version=version, notes=str(payload.get("body") or "").strip(), page_url=page_url)
    for asset in payload.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not _INSTALLER_NAME.match(name) or not url.casefold().startswith(_DOWNLOAD_PREFIX):
            continue
        digest = str(asset.get("digest") or "")
        return UpdateInfo(
            version=version, notes=info.notes, page_url=page_url,
            installer_url=url, installer_name=name,
            installer_size=int(asset.get("size") or 0),
            sha256=digest.split(":", 1)[1].casefold() if digest.casefold().startswith("sha256:") else "",
        )
    return info


def _fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise UpdateError(f"The update server answered with error {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise UpdateError("Could not reach the update server. Check the internet connection.") from exc


def check_for_update(current: str = APP_VERSION, fetch: Callable[[str], Any] = _fetch_json) -> UpdateInfo | None:
    """Return the latest published release when it is newer than `current`."""

    info = release_from_payload(fetch(LATEST_RELEASE_API))
    return info if info is not None and is_newer(info.version, current) else None


def _open(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    return urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS)


def download_installer(
    info: UpdateInfo,
    directory: Path,
    progress: Callable[[int, int], None] | None = None,
    opener: Callable[[str], Any] = _open,
    cancelled: Callable[[], bool] = lambda: False,
) -> Path:
    """Download the release installer and confirm it is the published file."""

    if not info.installer_url.casefold().startswith(_DOWNLOAD_PREFIX) or not _INSTALLER_NAME.match(info.installer_name):
        raise UpdateError("This release has no installer that can be downloaded automatically.")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / info.installer_name
    partial = target.with_suffix(".part")
    digest = hashlib.sha256()
    received = 0
    try:
        with opener(info.installer_url) as response, partial.open("wb") as handle:
            while True:
                if cancelled():
                    raise UpdateError("Download cancelled.")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if progress is not None:
                    progress(received, info.installer_size)
        if info.installer_size and received != info.installer_size:
            raise UpdateError("The download was incomplete. Try again.")
        if info.sha256 and digest.hexdigest() != info.sha256:
            raise UpdateError("The downloaded installer did not match the published file and was discarded.")
        partial.replace(target)
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError("The download failed. Check the internet connection and try again.") from exc
    return target
