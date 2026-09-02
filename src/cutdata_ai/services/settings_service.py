"""Load and save user settings without exposing API keys in logs or source."""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
from dataclasses import asdict
from typing import Any

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


class SettingsService:
    def __init__(self, database: Database):
        self.database = database

    def load(self) -> AppSettings:
        mock_default = not bool(os.environ.get("OPENAI_API_KEY"))
        return AppSettings(
            model=self.database.get_setting("model", DEFAULT_MODEL) or DEFAULT_MODEL,
            reasoning_effort=self.database.get_setting("reasoning_effort", DEFAULT_REASONING_EFFORT)
            or DEFAULT_REASONING_EFFORT,
            mock_mode=(self.database.get_setting("mock_mode", "1" if mock_default else "0") or "0").casefold()
            in {"1", "true", "yes"},
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
        environment_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if environment_key:
            return environment_key
        protected = self.database.get_setting("openai_api_key", "") or ""
        return SecretStore.unprotect(protected)

    def save_api_key(self, api_key: str) -> None:
        if not api_key.strip():
            self.database.set_setting("openai_api_key", "")
            return
        protected = SecretStore.protect(api_key.strip())
        if protected:
            self.database.set_setting("openai_api_key", protected)
