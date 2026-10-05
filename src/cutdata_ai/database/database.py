"""SQLite persistence for cache, tools, preferences, and workshop settings."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..config.constants import MACHINE_PROFILES, PROMPT_VERSION, SCHEMA_VERSION


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _ClosingConnection(sqlite3.Connection):
    """Commit or roll back like sqlite3, then release the file handle."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Database:
    """A small SQLite repository using short-lived connections.

    Opening a connection per operation keeps the class safe when a calculation
    worker thread and the Qt UI both access the database.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialise()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15, factory=_ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialise(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cache_records (
                    request_hash TEXT PRIMARY KEY,
                    normalized_request_json TEXT NOT NULL,
                    returned_data_json TEXT NOT NULL,
                    validated_data_json TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    response_id TEXT NOT NULL DEFAULT '',
                    usage_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    use_count INTEGER NOT NULL DEFAULT 1,
                    is_mock INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_cache_versions
                    ON cache_records(prompt_version, schema_version);

                CREATE TABLE IF NOT EXISTS recent_calculations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_hash TEXT NOT NULL,
                    normalized_request_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS saved_tools (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    tool_type TEXT NOT NULL,
                    tool_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    use_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS preferred_results (
                    request_hash TEXT PRIMARY KEY,
                    normalized_request_json TEXT NOT NULL,
                    ai_result_json TEXT NOT NULL,
                    preferred_result_json TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    use_count INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS machine_profiles (
                    name TEXT PRIMARY KEY COLLATE NOCASE,
                    max_rpm REAL NOT NULL,
                    max_feed_mm_min REAL NOT NULL,
                    spindle_power_kw REAL,
                    coolant_capability TEXT NOT NULL,
                    rigidity TEXT NOT NULL
                );
                """
            )
            for profile in MACHINE_PROFILES:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO machine_profiles
                    (name, max_rpm, max_feed_mm_min, spindle_power_kw,
                     coolant_capability, rigidity)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile["name"],
                        profile["max_rpm"],
                        profile["max_feed_mm_min"],
                        profile["spindle_power_kw"],
                        profile["coolant_capability"],
                        profile["rigidity"],
                    ),
                )
            # 0.1.12 corrects the shipped VF-2 limit.  Only the exact old
            # shipped value is migrated; edited/custom limits are preserved.
            connection.execute(
                """
                UPDATE machine_profiles
                SET max_rpm = 8000.0
                WHERE name = 'HAAS VF-2' COLLATE NOCASE
                  AND max_rpm = 12000.0
                  AND max_feed_mm_min = 10000.0
                  AND spindle_power_kw IS NULL
                  AND coolant_capability = 'Flood coolant; internal coolant configurable'
                  AND rigidity = 'medium-high'
                """
            )
            recent_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(recent_calculations)")
            }
            if "model" not in recent_columns:
                # Existing history stays untouched; blank means its model was
                # not recorded by the older schema.
                connection.execute(
                    "ALTER TABLE recent_calculations ADD COLUMN model TEXT NOT NULL DEFAULT ''"
                )

        # Keep the retired saved_tools table untouched for compatibility.
        # The normalized library is additive and its stable seeds are inserted
        # only when their seed_key is absent.
        from ..services.tool_library import initialize_tool_library

        initialize_tool_library(self)

    # Cache ---------------------------------------------------------------
    def get_cache_record(
        self,
        request_hash: str,
        prompt_version: str = PROMPT_VERSION,
        schema_version: str = SCHEMA_VERSION,
        model: str | None = None,
    ):
        with self.connect() as connection:
            query = """
                SELECT * FROM cache_records
                WHERE request_hash = ? AND prompt_version = ? AND schema_version = ?
            """
            parameters: tuple[str, ...] = (request_hash, prompt_version, schema_version)
            if model is not None:
                query += " AND model = ?"
                parameters += (model,)
            row = connection.execute(query, parameters).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE cache_records SET last_used_at = ?, use_count = use_count + 1 WHERE request_hash = ?",
                (utc_now(), request_hash),
            )
            return dict(row)

    def put_cache_record(
        self,
        request_hash: str,
        normalized_request: dict[str, Any],
        returned_data: dict[str, Any],
        validated_data: dict[str, Any],
        model: str,
        prompt_version: str = PROMPT_VERSION,
        schema_version: str = SCHEMA_VERSION,
        response_id: str = "",
        usage: dict[str, Any] | None = None,
        is_mock: bool = False,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO cache_records (
                    request_hash, normalized_request_json, returned_data_json,
                    validated_data_json, model, prompt_version, schema_version,
                    response_id, usage_json, created_at, last_used_at, use_count, is_mock
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(request_hash) DO UPDATE SET
                    normalized_request_json = excluded.normalized_request_json,
                    returned_data_json = excluded.returned_data_json,
                    validated_data_json = excluded.validated_data_json,
                    model = excluded.model,
                    prompt_version = excluded.prompt_version,
                    schema_version = excluded.schema_version,
                    response_id = excluded.response_id,
                    usage_json = excluded.usage_json,
                    last_used_at = excluded.last_used_at,
                    is_mock = excluded.is_mock
                """,
                (
                    request_hash,
                    json.dumps(normalized_request, ensure_ascii=False, sort_keys=True),
                    json.dumps(returned_data, ensure_ascii=False, sort_keys=True),
                    json.dumps(validated_data, ensure_ascii=False, sort_keys=True),
                    model,
                    prompt_version,
                    schema_version,
                    response_id,
                    json.dumps(usage or {}, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                    int(is_mock),
                ),
            )

    # Recent calculations -------------------------------------------------
    def add_recent(
        self,
        request_hash: str,
        normalized_request: dict[str, Any],
        result: dict[str, Any],
        source: str,
        model: str = "",
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO recent_calculations
                (request_hash, normalized_request_json, result_json, source, created_at, model)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    request_hash,
                    json.dumps(normalized_request, ensure_ascii=False, sort_keys=True),
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    source,
                    utc_now(),
                    model,
                ),
            )
            connection.execute(
                """
                DELETE FROM recent_calculations
                WHERE id NOT IN (SELECT id FROM recent_calculations ORDER BY id DESC LIMIT 25)
                """
            )

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM recent_calculations ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            ]

    # Saved tools ---------------------------------------------------------
    def save_tool(self, name: str, tool_type: str, tool: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO saved_tools (name, tool_type, tool_json, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    tool_type = excluded.tool_type,
                    tool_json = excluded.tool_json,
                    last_used_at = excluded.last_used_at
                """,
                (name.strip(), tool_type, json.dumps(tool, ensure_ascii=False, sort_keys=True), now, now),
            )

    def saved_tools(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM saved_tools ORDER BY name").fetchall()]

    def get_saved_tool(self, tool_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM saved_tools WHERE id = ?", (tool_id,)).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE saved_tools SET last_used_at = ?, use_count = use_count + 1 WHERE id = ?",
                (utc_now(), tool_id),
            )
            return dict(row)

    def delete_saved_tool(self, tool_id: int) -> None:
        """Remove one saved tool from the local tool library."""

        with self.connect() as connection:
            connection.execute("DELETE FROM saved_tools WHERE id = ?", (int(tool_id),))

    # Workshop preferences -----------------------------------------------
    def get_preferred_result(
        self,
        request_hash: str,
        prompt_version: str = PROMPT_VERSION,
        schema_version: str = SCHEMA_VERSION,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM preferred_results
                WHERE request_hash = ? AND prompt_version = ? AND schema_version = ?
                """,
                (request_hash, prompt_version, schema_version),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE preferred_results SET last_used_at = ?, use_count = use_count + 1 WHERE request_hash = ?",
                (utc_now(), request_hash),
            )
            return dict(row)

    def save_preferred_result(
        self,
        request_hash: str,
        normalized_request: dict[str, Any],
        ai_result: dict[str, Any],
        preferred_result: dict[str, Any],
        prompt_version: str = PROMPT_VERSION,
        schema_version: str = SCHEMA_VERSION,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO preferred_results
                (request_hash, normalized_request_json, ai_result_json,
                 preferred_result_json, prompt_version, schema_version,
                 created_at, last_used_at, use_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(request_hash) DO UPDATE SET
                    normalized_request_json = excluded.normalized_request_json,
                    ai_result_json = excluded.ai_result_json,
                    preferred_result_json = excluded.preferred_result_json,
                    prompt_version = excluded.prompt_version,
                    schema_version = excluded.schema_version,
                    last_used_at = excluded.last_used_at
                """,
                (
                    request_hash,
                    json.dumps(normalized_request, ensure_ascii=False, sort_keys=True),
                    json.dumps(ai_result, ensure_ascii=False, sort_keys=True),
                    json.dumps(preferred_result, ensure_ascii=False, sort_keys=True),
                    prompt_version,
                    schema_version,
                    now,
                    now,
                ),
            )

    # Settings and machine profiles --------------------------------------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO app_settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def machine_profiles(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM machine_profiles ORDER BY rowid").fetchall()]

    def update_machine_profile(self, name: str, values: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE machine_profiles SET max_rpm = ?, max_feed_mm_min = ?,
                    spindle_power_kw = ?, coolant_capability = ?, rigidity = ?
                WHERE name = ?
                """,
                (
                    float(values.get("max_rpm", 0)),
                    float(values.get("max_feed_mm_min", 0)),
                    values.get("spindle_power_kw"),
                    str(values.get("coolant_capability", "")),
                    str(values.get("rigidity", "medium")),
                    name,
                ),
            )
