"""Load and save user settings without exposing API keys in logs or source."""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import hmac
import json
import os
from dataclasses import asdict, dataclass

from ..config.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from ..config.settings import AppSettings, normalise_appearance
from ..database.database import Database


class SecretStore:
    """Use Windows DPAPI for the locally saved API key.

    On non-Windows development environments the key is intentionally not
    persisted; OPENAI_API_KEY remains the portable option.
    """

    PREFIX = "dpapi:"

    @classmethod
    def protect(cls, value: str) -> str:
        if os.name != "nt":
            return ""
        try:
            return cls.PREFIX + base64.b64encode(cls._crypt(value.encode("utf-8"), True)).decode("ascii")
        except Exception:
            return ""

    @classmethod
    def unprotect(cls, value: str) -> str:
        if not value or not value.startswith(cls.PREFIX) or os.name != "nt":
            return ""
        try:
            data = base64.b64decode(value[len(cls.PREFIX) :])
            return cls._crypt(data, False).decode("utf-8")
        except Exception:
            return ""

    @staticmethod
    def _crypt(data: bytes, protect: bool) -> bytes:
        class Blob(ctypes.Structure):
            _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

        input_buffer = ctypes.create_string_buffer(data)
        input_blob = Blob(len(data), ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_byte)))
        output_blob = Blob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        function.argtypes = [
            ctypes.POINTER(Blob),
            ctypes.wintypes.LPCWSTR,
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(Blob),
        ]
        function.restype = ctypes.wintypes.BOOL
        if not function(ctypes.byref(input_blob), "CutData AI API key", None, None, None, 0, ctypes.byref(output_blob)):
            raise OSError("Windows DPAPI could not protect the API key")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            kernel32.LocalFree(output_blob.pbData)


API_KEY_SOURCE_ENVIRONMENT = "environment"
API_KEY_SOURCE_SAVED = "saved"
API_KEY_SOURCE_NONE = "none"


@dataclass(frozen=True)
class ApiKeyStatus:
    """Safe API-key metadata for the UI.

    This deliberately contains no key material.  It is safe to pass between
    the settings service and presentation code.
    """

    saved_configured: bool
    environment_detected: bool
    source: str
    keys_match: bool | None = None
    selected_source_configured: bool = False


class SettingsService:
    def __init__(self, database: Database):
        self.database = database

    def load(self) -> AppSettings:
        stored_mock_mode = self.database.get_setting("mock_mode")
        api_key_source = self.get_active_api_key_source()
        mock_default = api_key_source == API_KEY_SOURCE_NONE
        mock_mode = (
            self._as_bool(stored_mock_mode)
            if stored_mock_mode is not None
            else mock_default
        )
        return AppSettings(
            model=self.database.get_setting("model", DEFAULT_MODEL) or DEFAULT_MODEL,
            reasoning_effort=self.database.get_setting("reasoning_effort", DEFAULT_REASONING_EFFORT)
            or DEFAULT_REASONING_EFFORT,
            appearance=normalise_appearance(self.database.get_setting("appearance", "light")),
            mock_mode=mock_mode,
            last_machine=self.database.get_setting("last_machine", "Generic CNC Mill") or "Generic CNC Mill",
            last_material=self.database.get_setting("last_material", "Mild Steel") or "Mild Steel",
            last_tool_type=self.database.get_setting("last_tool_type", "Drill") or "Drill",
            last_coolant=self.database.get_setting("last_coolant", "Flood coolant") or "Flood coolant",
            api_key_source=api_key_source,
        )

    def save(self, settings: AppSettings) -> None:
        settings.appearance = normalise_appearance(settings.appearance)
        values = asdict(settings)
        for key, value in values.items():
            if key == "api_key_source" and value not in {
                API_KEY_SOURCE_ENVIRONMENT,
                API_KEY_SOURCE_SAVED,
                API_KEY_SOURCE_NONE,
            }:
                # Preserve the selected source for callers that construct a
                # partial AppSettings object without an API-source choice.
                continue
            self.database.set_setting(key, ("1" if value else "0") if isinstance(value, bool) else str(value))

    def load_json_setting(self, key: str, default=None):
        """Load an opaque JSON setting without allowing bad state to block startup."""

        raw = self.database.get_setting(key)
        if not raw:
            return default
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return default

    def save_json_setting(self, key: str, value) -> None:
        """Save a JSON-compatible setting with stable ordering."""

        self.database.set_setting(
            key,
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )

    def get_api_key(self) -> str:
        """Return the key selected by the persisted active source."""

        source = self.get_active_api_key_source()
        environment_key, saved_key = self._read_api_keys()
        if source == API_KEY_SOURCE_ENVIRONMENT:
            return environment_key
        if source == API_KEY_SOURCE_SAVED:
            return saved_key
        return ""

    def get_active_api_key(self) -> str:
        """Alias used by calculation and connection-test call sites."""

        return self.get_api_key()

    def get_environment_api_key(self) -> str:
        """Return the environment key, if present, without exposing it to UI code."""

        return os.environ.get("OPENAI_API_KEY", "").strip()

    def get_saved_api_key(self) -> str:
        """Return the decrypted local key, if present, for service construction."""

        protected = self.database.get_setting("openai_api_key", "") or ""
        return str(SecretStore.unprotect(protected) or "").strip()

    def get_api_key_source(self) -> str:
        """Backward-compatible alias for the explicit active source."""

        return self.get_active_api_key_source()

    def get_active_api_key_source(self) -> str:
        """Return the selected source without silently falling back.

        Existing installations are migrated once.  If both locations contain
        different keys, the saved key is selected so the previous UI action of
        entering a local key remains authoritative; matching keys retain the
        previous environment-first behaviour.
        """

        environment_key, saved_key = self._read_api_keys()
        stored = self.database.get_setting("api_key_source")
        if stored in {
            API_KEY_SOURCE_ENVIRONMENT,
            API_KEY_SOURCE_SAVED,
            API_KEY_SOURCE_NONE,
        }:
            if stored == API_KEY_SOURCE_ENVIRONMENT and not environment_key:
                return API_KEY_SOURCE_NONE
            if stored == API_KEY_SOURCE_SAVED and not saved_key:
                return API_KEY_SOURCE_NONE
            return stored

        if environment_key and saved_key:
            source = (
                API_KEY_SOURCE_ENVIRONMENT
                if hmac.compare_digest(environment_key, saved_key)
                else API_KEY_SOURCE_SAVED
            )
        elif saved_key:
            source = API_KEY_SOURCE_SAVED
        elif environment_key:
            source = API_KEY_SOURCE_ENVIRONMENT
        else:
            source = API_KEY_SOURCE_NONE
        self.database.set_setting("api_key_source", source)
        return source

    def set_api_key_source(self, source: str) -> str:
        """Persist a safe, supported active-source value."""

        normalised = str(source or "").strip().casefold()
        if normalised not in {
            API_KEY_SOURCE_ENVIRONMENT,
            API_KEY_SOURCE_SAVED,
            API_KEY_SOURCE_NONE,
        }:
            normalised = API_KEY_SOURCE_NONE
        self.database.set_setting("api_key_source", normalised)
        return normalised

    def get_api_key_status(self) -> ApiKeyStatus:
        """Return key presence/source metadata without returning key material."""

        environment_key, saved_key = self._read_api_keys()
        source = self.get_active_api_key_source()
        keys_match = None
        if environment_key and saved_key:
            keys_match = hmac.compare_digest(environment_key, saved_key)
        selected_configured = bool(
            (source == API_KEY_SOURCE_ENVIRONMENT and environment_key)
            or (source == API_KEY_SOURCE_SAVED and saved_key)
        )
        return ApiKeyStatus(
            saved_configured=bool(saved_key),
            environment_detected=bool(environment_key),
            source=source,
            keys_match=keys_match,
            selected_source_configured=selected_configured,
        )

    def save_api_key(self, api_key: str) -> None:
        if not api_key.strip():
            self.clear_saved_api_key()
            return
        protected = SecretStore.protect(api_key.strip())
        if protected:
            self.database.set_setting("openai_api_key", protected)
            stored = self.database.get_setting("api_key_source")
            if stored in {None, "", API_KEY_SOURCE_NONE}:
                self.set_api_key_source(API_KEY_SOURCE_SAVED)

    def clear_saved_api_key(self) -> None:
        """Remove only the locally saved key; environment variables are untouched."""

        self.database.set_setting("openai_api_key", "")
        if self.database.get_setting("api_key_source") == API_KEY_SOURCE_SAVED:
            self.set_api_key_source(
                API_KEY_SOURCE_ENVIRONMENT
                if self.get_environment_api_key()
                else API_KEY_SOURCE_NONE
            )

    @staticmethod
    def _as_bool(value: str | None) -> bool:
        return (value or "").casefold() in {"1", "true", "yes", "on"}

    def _read_api_keys(self) -> tuple[str, str]:
        """Read both key locations together without exposing their values to UI metadata."""

        return self.get_environment_api_key(), self.get_saved_api_key()
