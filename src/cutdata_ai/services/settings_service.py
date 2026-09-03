"""Load and save user settings without exposing API keys in logs or source."""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import os
from dataclasses import asdict, dataclass

from ..config.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from ..config.settings import AppSettings
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


class SettingsService:
    def __init__(self, database: Database):
        self.database = database

    def load(self) -> AppSettings:
        stored_mock_mode = self.database.get_setting("mock_mode")
        mock_default = self.get_api_key_source() == API_KEY_SOURCE_NONE
        mock_mode = (
            self._as_bool(stored_mock_mode)
            if stored_mock_mode is not None
            else mock_default
        )
        return AppSettings(
            model=self.database.get_setting("model", DEFAULT_MODEL) or DEFAULT_MODEL,
            reasoning_effort=self.database.get_setting("reasoning_effort", DEFAULT_REASONING_EFFORT)
            or DEFAULT_REASONING_EFFORT,
            mock_mode=mock_mode,
            last_machine=self.database.get_setting("last_machine", "Generic CNC Mill") or "Generic CNC Mill",
            last_material=self.database.get_setting("last_material", "Mild Steel") or "Mild Steel",
            last_tool_type=self.database.get_setting("last_tool_type", "Drill") or "Drill",
            last_coolant=self.database.get_setting("last_coolant", "Flood coolant") or "Flood coolant",
        )

    def save(self, settings: AppSettings) -> None:
        values = asdict(settings)
        for key, value in values.items():
            self.database.set_setting(key, ("1" if value else "0") if isinstance(value, bool) else str(value))

    def get_api_key(self) -> str:
        environment_key, saved_key = self._read_api_keys()
        return environment_key or saved_key

    def get_environment_api_key(self) -> str:
        """Return the environment key, if present, without exposing it to UI code."""

        return os.environ.get("OPENAI_API_KEY", "").strip()

    def get_saved_api_key(self) -> str:
        """Return the decrypted local key, if present, for service construction."""

        protected = self.database.get_setting("openai_api_key", "") or ""
        return str(SecretStore.unprotect(protected) or "").strip()

    def get_api_key_source(self) -> str:
        """Return the active source using the documented priority order.

        Environment key -> encrypted saved key -> no key.
        """

        environment_key, saved_key = self._read_api_keys()
        if environment_key:
            return API_KEY_SOURCE_ENVIRONMENT
        if saved_key:
            return API_KEY_SOURCE_SAVED
        return API_KEY_SOURCE_NONE

    def get_api_key_status(self) -> ApiKeyStatus:
        """Return key presence/source metadata without returning key material."""

        environment_key, saved_key = self._read_api_keys()
        if environment_key:
            source = API_KEY_SOURCE_ENVIRONMENT
        elif saved_key:
            source = API_KEY_SOURCE_SAVED
        else:
            source = API_KEY_SOURCE_NONE
        return ApiKeyStatus(
            saved_configured=bool(saved_key),
            environment_detected=bool(environment_key),
            source=source,
        )

    def save_api_key(self, api_key: str) -> None:
        if not api_key.strip():
            self.clear_saved_api_key()
            return
        protected = SecretStore.protect(api_key.strip())
        if protected:
            self.database.set_setting("openai_api_key", protected)

    def clear_saved_api_key(self) -> None:
        """Remove only the locally saved key; environment variables are untouched."""

        self.database.set_setting("openai_api_key", "")

    @staticmethod
    def _as_bool(value: str | None) -> bool:
        return (value or "").casefold() in {"1", "true", "yes", "on"}

    def _read_api_keys(self) -> tuple[str, str]:
        """Read both key locations once while keeping priority in one place."""

        return self.get_environment_api_key(), self.get_saved_api_key()
