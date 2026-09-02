"""User settings and platform paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT


def default_data_dir() -> Path:
    override = os.environ.get("CUTDATA_AI_DATA_DIR")
    if override:
        return Path(override).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "CutData AI"
    return Path.home() / ".cutdata-ai"


@dataclass
class AppSettings:
    """Settings that affect the current calculation session."""

    model: str = DEFAULT_MODEL
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    mock_mode: bool = False
    last_machine: str = "Generic CNC Mill"
    last_material: str = "Mild Steel"
    last_tool_type: str = "Drill"
    last_coolant: str = "Flood coolant"

