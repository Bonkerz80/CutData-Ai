"""Normalized workshop tool/insert library and its versioned starter records."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


TOOL_FIELDS = (
    "display_name", "manufacturer", "product_family", "model_code",
    "manufacturer_part_number", "tool_type", "diameter_mm",
    "effective_cutting_diameter_mm", "flute_count", "insert_count",
    "linked_insert_id", "tool_material", "coating", "corner_radius_mm",
    "ball_radius_mm", "shank_diameter_mm", "cutting_edge_length_mm",
    "overall_length_mm", "default_stickout_mm", "approach_angle_deg", "hand",
    "holder_interface", "notes", "source_type", "source_url", "source_title",
    "source_retrieved_at", "source_text", "confidence", "needs_review",
    "field_provenance", "details",
)
INSERT_FIELDS = (
    "display_name", "manufacturer", "product_family", "designation",
    "iso_designation", "ansi_designation", "manufacturer_part_number", "grade",
    "geometry", "chipbreaker", "shape", "insert_size", "inscribed_circle_mm",
    "thickness_mm", "corner_radius_mm", "cutting_edge_count", "coating",
    "substrate", "iso_material_groups", "manufacturer_application",
    "manufacturer_notes", "source_type", "source_url", "source_title",
    "source_retrieved_at", "source_text", "confidence", "needs_review",
    "field_provenance", "details",
)

_JSON_FIELDS = {"field_provenance", "details", "iso_material_groups"}
_FLOAT_FIELDS = {
    "diameter_mm", "effective_cutting_diameter_mm", "corner_radius_mm",
    "ball_radius_mm", "shank_diameter_mm", "cutting_edge_length_mm",
    "overall_length_mm", "default_stickout_mm", "approach_angle_deg",
    "inscribed_circle_mm", "thickness_mm",
}
_INT_FIELDS = {"flute_count", "insert_count", "cutting_edge_count"}
_SYSTEM_FIELDS = {
    "id", "created_at", "updated_at", "user_modified", "seed_key", "revision",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _decode_row(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    value = dict(row)
    for field in _JSON_FIELDS:
        raw = value.pop(field + "_json", None)
        if raw is None and field in value:
            continue
        try:
            value[field] = json.loads(raw or ("[]" if field == "iso_material_groups" else "{}"))
        except (TypeError, json.JSONDecodeError):
            value[field] = [] if field == "iso_material_groups" else {}
    for field in ("needs_review", "user_modified"):
        if field in value:
            value[field] = bool(value[field])
    return value


def _stored_value(field: str, value: Any) -> Any:
    if field in _JSON_FIELDS:
        if field == "iso_material_groups" and value is None:
            value = []
        return _json(value if value is not None else {})
    if field == "needs_review":
        return int(bool(value))
    if field in _FLOAT_FIELDS:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field.replace('_', ' ').title()} must be a number.") from exc
    if field in _INT_FIELDS:
        if value in (None, ""):
            return None
        try:
            number = float(value)
            if not number.is_integer():
                raise ValueError
            return int(number)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field.replace('_', ' ').title()} must be a whole number.") from exc
    if field == "linked_insert_id":
        return int(value) if value not in (None, "") else None
    if value is None:
        return "" if field not in {"diameter_mm", "flute_count", "insert_count"} else None
    return str(value).strip()


class ToolLibraryService:
    """CRUD operations for distinct cutter bodies, inserts and observations."""

    def __init__(self, database):
        self.database = database

    def list_tools(self, search: str = "") -> list[dict[str, Any]]:
        query = "SELECT * FROM tool_library"
        params: tuple[Any, ...] = ()
        if search.strip():
            match = f"%{search.strip()}%"
            query += " WHERE display_name LIKE ? COLLATE NOCASE OR manufacturer LIKE ? COLLATE NOCASE OR model_code LIKE ? COLLATE NOCASE OR manufacturer_part_number LIKE ? COLLATE NOCASE OR tool_type LIKE ? COLLATE NOCASE"
            params = (match, match, match, match, match)
        query += " ORDER BY display_name COLLATE NOCASE, id"
        with self.database.connect() as connection:
            return [_decode_row(row) for row in connection.execute(query, params).fetchall()]

    def list_inserts(self, search: str = "") -> list[dict[str, Any]]:
        query = "SELECT * FROM tool_inserts"
        params: tuple[Any, ...] = ()
        if search.strip():
            match = f"%{search.strip()}%"
            query += " WHERE display_name LIKE ? COLLATE NOCASE OR manufacturer LIKE ? COLLATE NOCASE OR designation LIKE ? COLLATE NOCASE OR grade LIKE ? COLLATE NOCASE OR manufacturer_part_number LIKE ? COLLATE NOCASE"
            params = (match, match, match, match, match)
        query += " ORDER BY display_name COLLATE NOCASE, id"
        with self.database.connect() as connection:
            return [_decode_row(row) for row in connection.execute(query, params).fetchall()]

    def get_tool(self, tool_id: int) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            return _decode_row(connection.execute("SELECT * FROM tool_library WHERE id=?", (int(tool_id),)).fetchone())

    def get_insert(self, insert_id: int) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            return _decode_row(connection.execute("SELECT * FROM tool_inserts WHERE id=?", (int(insert_id),)).fetchone())

    def _save(self, table: str, fields: tuple[str, ...], values: dict[str, Any], record_id: int | None = None) -> int:
        now = _now()
        with self.database.connect() as connection:
            if record_id is not None:
                old = connection.execute(f"SELECT * FROM {table} WHERE id=?", (int(record_id),)).fetchone()
                if old is None:
                    raise ValueError("That library record no longer exists.")
                previous = _decode_row(old) or {}
                merged = {field: previous.get(field) for field in fields}
                merged.update({key: value for key, value in values.items() if key in fields})
                if not str(merged.get("display_name", "")).strip():
                    raise ValueError("A display name is required.")
                if "field_provenance" not in values:
                    provenance = dict(previous.get("field_provenance") or {})
                    for key, value in values.items():
                        if key in fields and key not in {"field_provenance", "details"} and previous.get(key) != value:
                            provenance[key] = {
                                "status": "user_supplied", "confidence": "high",
                                "evidence": "Edited by the workshop user", "source_url": "",
                            }
                    merged["field_provenance"] = provenance
                assignments = [f"{field + '_json' if field in _JSON_FIELDS else field}=?" for field in fields]
                encoded = [_stored_value(field, merged.get(field)) for field in fields]
                connection.execute(
                    f"UPDATE {table} SET {', '.join(assignments)}, updated_at=?, user_modified=1, revision=revision+1 WHERE id=?",
                    (*encoded, now, int(record_id)),
                )
                return int(record_id)

            if not str(values.get("display_name", "")).strip():
                raise ValueError("A display name is required.")
            payload = {field: values.get(field) for field in fields}
            if "field_provenance" in fields and not values.get("field_provenance"):
                known = [
                    field for field in fields
                    if field not in {"field_provenance", "details"}
                    and payload.get(field) not in (None, "", [], {})
                ]
                payload["field_provenance"] = {
                    field: {"status": "user_supplied", "confidence": "high", "evidence": "Entered by the workshop user", "source_url": ""}
                    for field in known
                }
            columns = [field + "_json" if field in _JSON_FIELDS else field for field in fields]
            seed_key = values.get("seed_key")
            if seed_key:
                columns.append("seed_key")
            columns.extend(("created_at", "updated_at", "user_modified", "revision"))
            encoded = [_stored_value(field, payload.get(field)) for field in fields]
            if seed_key:
                encoded.append(str(seed_key))
            encoded.extend((now, now, int(bool(values.get("user_modified", False))), 1))
            placeholders = ",".join("?" for _ in columns)
            cursor = connection.execute(
                f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})", encoded
            )
            return int(cursor.lastrowid)

    def add_tool(self, values: dict[str, Any]) -> dict[str, Any]:
        record_id = self._save("tool_library", TOOL_FIELDS, values)
        return self.get_tool(record_id)  # type: ignore[return-value]

    def update_tool(self, tool_id: int, values: dict[str, Any]) -> dict[str, Any]:
        self._save("tool_library", TOOL_FIELDS, values, tool_id)
        return self.get_tool(tool_id)  # type: ignore[return-value]

    def add_insert(self, values: dict[str, Any]) -> dict[str, Any]:
        record_id = self._save("tool_inserts", INSERT_FIELDS, values)
        return self.get_insert(record_id)  # type: ignore[return-value]

    def update_insert(self, insert_id: int, values: dict[str, Any]) -> dict[str, Any]:
        self._save("tool_inserts", INSERT_FIELDS, values, insert_id)
        return self.get_insert(insert_id)  # type: ignore[return-value]

    def duplicate_tool(self, tool_id: int) -> dict[str, Any]:
        source = self.get_tool(tool_id)
        if source is None:
            raise ValueError("That tool no longer exists.")
        copy = {key: value for key, value in source.items() if key in TOOL_FIELDS}
        copy["display_name"] = f"{source['display_name']} (copy)"
        copy["user_modified"] = True
        return self.add_tool(copy)

    def duplicate_insert(self, insert_id: int) -> dict[str, Any]:
        source = self.get_insert(insert_id)
        if source is None:
            raise ValueError("That insert no longer exists.")
        copy = {key: value for key, value in source.items() if key in INSERT_FIELDS}
        copy["display_name"] = f"{source['display_name']} (copy)"
        copy["user_modified"] = True
        return self.add_insert(copy)

    def delete_tool(self, tool_id: int) -> None:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM tool_library WHERE id=?", (int(tool_id),))

    def delete_insert(self, insert_id: int) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE tool_library SET linked_insert_id=NULL, needs_review=1, updated_at=?, revision=revision+1 WHERE linked_insert_id=?",
                (_now(), int(insert_id)),
            )
            connection.execute("DELETE FROM tool_inserts WHERE id=?", (int(insert_id),))

    def tool_snapshot(self, tool_id: int) -> dict[str, Any] | None:
        tool = self.get_tool(tool_id)
        if tool is None:
            return None
        fields = (
            "display_name", "manufacturer", "product_family", "model_code",
            "manufacturer_part_number", "tool_type", "diameter_mm",
            "effective_cutting_diameter_mm", "flute_count", "insert_count",
            "tool_material", "coating", "corner_radius_mm", "ball_radius_mm",
            "shank_diameter_mm", "cutting_edge_length_mm", "overall_length_mm",
            "default_stickout_mm", "approach_angle_deg", "hand", "holder_interface",
            "notes", "field_provenance", "confidence", "needs_review", "revision",
        )
        snapshot = {field: tool.get(field) for field in fields}
        snapshot["library_id"] = tool["id"]
        # Thread facts are only added when recorded, so other tools keep the
        # same snapshot (and cached results) as before.
        details = tool.get("details") or {}
        for key in ("thread_size", "thread_pitch_mm"):
            if details.get(key) not in (None, ""):
                snapshot[key] = details[key]
        snapshot["insert"] = None
        if tool.get("linked_insert_id"):
            insert = self.get_insert(int(tool["linked_insert_id"]))
            if insert:
                insert_fields = (
                    "display_name", "manufacturer", "product_family", "designation",
                    "iso_designation", "ansi_designation", "manufacturer_part_number",
                    "grade", "geometry", "chipbreaker", "shape", "insert_size",
                    "inscribed_circle_mm", "thickness_mm", "corner_radius_mm",
                    "cutting_edge_count", "coating", "substrate", "iso_material_groups",
                    "manufacturer_application", "manufacturer_notes", "field_provenance",
                    "confidence", "needs_review", "revision",
                )
                snapshot["insert"] = {field: insert.get(field) for field in insert_fields}
                snapshot["insert"]["library_id"] = insert["id"]
        return snapshot

    def observations_for_tool(self, tool_id: int, limit: int = 20) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            records = [dict(row) for row in connection.execute(
                "SELECT * FROM workshop_observations WHERE tool_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
                (int(tool_id), max(0, int(limit))),
            ).fetchall()]
        for record in records:
            record["user_modified"] = bool(record.get("user_modified"))
        return records

    def add_observation(self, tool_id: int, note: str, category: str = "Observation", **actuals) -> int:
        note = str(note or "").strip()
        if not note:
            raise ValueError("Enter a workshop observation.")
        allowed = ("actual_rpm", "actual_feed_mm_min", "actual_doc_mm", "actual_engagement_mm")
        values = {key: actuals.get(key) for key in allowed}
        now = _now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO workshop_observations
                   (tool_id, category, note, actual_rpm, actual_feed_mm_min, actual_doc_mm,
                    actual_engagement_mm, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (int(tool_id), str(category), note,
                 values["actual_rpm"], values["actual_feed_mm_min"], values["actual_doc_mm"],
                 values["actual_engagement_mm"], now, now),
            )
            return int(cursor.lastrowid)

    def update_observation(self, observation_id: int, note: str, category: str = "Observation", **actuals) -> None:
        note = str(note or "").strip()
        if not note:
            raise ValueError("Enter a workshop observation.")
        allowed = ("actual_rpm", "actual_feed_mm_min", "actual_doc_mm", "actual_engagement_mm")
        with self.database.connect() as connection:
            connection.execute(
                """UPDATE workshop_observations SET category=?, note=?, actual_rpm=?, actual_feed_mm_min=?,
                   actual_doc_mm=?, actual_engagement_mm=?, updated_at=?, user_modified=1 WHERE id=?""",
                (str(category), note, *(actuals.get(key) for key in allowed), _now(), int(observation_id)),
            )

    def delete_observation(self, observation_id: int) -> None:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM workshop_observations WHERE id=?", (int(observation_id),))


def _ddl(database) -> None:
    with database.connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tool_inserts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                display_name TEXT NOT NULL,
                manufacturer TEXT NOT NULL DEFAULT '', product_family TEXT NOT NULL DEFAULT '',
                designation TEXT NOT NULL DEFAULT '', iso_designation TEXT NOT NULL DEFAULT '',
                ansi_designation TEXT NOT NULL DEFAULT '', manufacturer_part_number TEXT NOT NULL DEFAULT '',
                grade TEXT NOT NULL DEFAULT '', geometry TEXT NOT NULL DEFAULT '',
                chipbreaker TEXT NOT NULL DEFAULT '', shape TEXT NOT NULL DEFAULT '',
                insert_size TEXT NOT NULL DEFAULT '', inscribed_circle_mm REAL, thickness_mm REAL,
                corner_radius_mm REAL, cutting_edge_count INTEGER, coating TEXT NOT NULL DEFAULT '',
                substrate TEXT NOT NULL DEFAULT '', iso_material_groups_json TEXT NOT NULL DEFAULT '[]',
                manufacturer_application TEXT NOT NULL DEFAULT '', manufacturer_notes TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT 'user_supplied', source_url TEXT NOT NULL DEFAULT '',
                source_title TEXT NOT NULL DEFAULT '', source_retrieved_at TEXT NOT NULL DEFAULT '',
                source_text TEXT NOT NULL DEFAULT '', field_provenance_json TEXT NOT NULL DEFAULT '{}',
                confidence TEXT NOT NULL DEFAULT 'unknown', needs_review INTEGER NOT NULL DEFAULT 0,
                details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                user_modified INTEGER NOT NULL DEFAULT 0, seed_key TEXT UNIQUE, revision INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_tool_inserts_name ON tool_inserts(display_name COLLATE NOCASE);
            CREATE TABLE IF NOT EXISTS tool_library (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                display_name TEXT NOT NULL,
                manufacturer TEXT NOT NULL DEFAULT '', product_family TEXT NOT NULL DEFAULT '',
                model_code TEXT NOT NULL DEFAULT '', manufacturer_part_number TEXT NOT NULL DEFAULT '',
                tool_type TEXT NOT NULL DEFAULT 'End Mill', diameter_mm REAL,
                effective_cutting_diameter_mm REAL, flute_count INTEGER, insert_count INTEGER,
                linked_insert_id INTEGER REFERENCES tool_inserts(id) ON DELETE SET NULL,
                tool_material TEXT NOT NULL DEFAULT '', coating TEXT NOT NULL DEFAULT '',
                corner_radius_mm REAL, ball_radius_mm REAL, shank_diameter_mm REAL,
                cutting_edge_length_mm REAL, overall_length_mm REAL, default_stickout_mm REAL,
                approach_angle_deg REAL, hand TEXT NOT NULL DEFAULT '', holder_interface TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '', source_type TEXT NOT NULL DEFAULT 'user_supplied',
                source_url TEXT NOT NULL DEFAULT '', source_title TEXT NOT NULL DEFAULT '',
                source_retrieved_at TEXT NOT NULL DEFAULT '', source_text TEXT NOT NULL DEFAULT '',
                field_provenance_json TEXT NOT NULL DEFAULT '{}', confidence TEXT NOT NULL DEFAULT 'unknown',
                needs_review INTEGER NOT NULL DEFAULT 0, details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, user_modified INTEGER NOT NULL DEFAULT 0,
                seed_key TEXT UNIQUE, revision INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_tool_library_name ON tool_library(display_name COLLATE NOCASE);
            CREATE TABLE IF NOT EXISTS workshop_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_id INTEGER NOT NULL REFERENCES tool_library(id) ON DELETE CASCADE,
                category TEXT NOT NULL DEFAULT 'Observation', note TEXT NOT NULL,
                actual_rpm REAL, actual_feed_mm_min REAL, actual_doc_mm REAL, actual_engagement_mm REAL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, user_modified INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_workshop_observations_tool ON workshop_observations(tool_id, created_at DESC);
            """
        )


def _seed_provenance(keys: tuple[str, ...], uncertain: tuple[str, ...] = ()) -> dict[str, dict[str, str]]:
    return {
        key: {
            "status": "user_supplied" if key not in uncertain else "unknown",
            "confidence": "high" if key not in uncertain else "low",
            "evidence": "Confirmed workshop information" if key not in uncertain else "Not supplied; verify before relying on it",
        }
        for key in keys
    }


def seed_default_library(database) -> None:
    """Insert confirmed starting tools once; later edits survive future runs."""
    service = ToolLibraryService(database)
    inserts = (
        {
            "seed_key": "insert.widia.xdpt11.wp25pm", "display_name": "WIDIA XDPT11 WP25PM",
            "manufacturer": "WIDIA", "product_family": "VSM11 application",
            "designation": "XDPT110408PDSRMM", "grade": "WP25PM",
            "manufacturer_part_number": "5415319", "manufacturer_notes": "Known in the workshop as the VSM11 insert family/application.",
            "confidence": "high", "needs_review": False,
            "field_provenance": _seed_provenance(("manufacturer", "product_family", "designation", "grade", "manufacturer_part_number", "manufacturer_notes")),
        },
        {
            "seed_key": "insert.widia.xdpt17.wp25pm", "display_name": "WIDIA XDPT17 WP25PM",
            "manufacturer": "WIDIA", "product_family": "VSM17 application",
            "designation": "XDPT170408PESRMM", "grade": "WP25PM",
            "manufacturer_part_number": "5987949", "corner_radius_mm": 0.8,
            "cutting_edge_count": 2, "geometry": "-MM",
            "manufacturer_notes": "Workshop description: medium/heavy general-purpose geometry. Coating unknown; verify before recording.",
            "confidence": "high", "needs_review": False,
            "field_provenance": _seed_provenance(("manufacturer", "product_family", "designation", "grade", "manufacturer_part_number", "corner_radius_mm", "cutting_edge_count", "geometry", "manufacturer_notes")),
        },
        {
            "seed_key": "insert.zccct.rdkw12.ybg205h", "display_name": "ZCC RDKW12 YBG205H",
            "manufacturer": "ZCC-CT", "designation": "RDKW12T3MO-1", "grade": "YBG205H",
            "shape": "Round", "inscribed_circle_mm": 12,
            "confidence": "high", "needs_review": False,
            "field_provenance": _seed_provenance(("manufacturer", "designation", "grade", "shape", "inscribed_circle_mm")),
        },
        {
            "seed_key": "insert.zccct.seht1204afsn.review", "display_name": "ZCC-CT SEHT1204AFSN — needs review",
            "manufacturer": "ZCC-CT", "designation": "SEHT1204AFSN", "grade": "YBG205",
            "manufacturer_notes": "Known marking/context: M20-M40. Previously used with a 50 mm 45-degree 4-tip face mill. No suffix or application details inferred.",
            "confidence": "low", "needs_review": True,
            "field_provenance": _seed_provenance(("manufacturer", "designation", "grade", "manufacturer_notes"), ("manufacturer_notes",)),
        },
    )
    insert_ids: dict[str, int] = {}
    for record in inserts:
        seed_key = record["seed_key"]
        existing = next((item for item in service.list_inserts() if item.get("seed_key") == seed_key), None)
        if existing is None:
            service.add_insert(record)
            existing = next(item for item in service.list_inserts() if item.get("seed_key") == seed_key)
        insert_ids[seed_key] = int(existing["id"])

    tools = (
        {"seed_key": "tool.widia.vsm11.20-tipped", "display_name": "20 Tipped", "manufacturer": "WIDIA", "product_family": "VSM11", "tool_type": "Indexable End Mill", "diameter_mm": 20, "insert_count": 2, "linked_insert_id": insert_ids["insert.widia.xdpt11.wp25pm"], "notes": "Shop shorthand: (20 Tipped)", "confidence": "high", "needs_review": False},
        {"seed_key": "tool.widia.vsm17.25-tipped", "display_name": "25 Tipped", "manufacturer": "WIDIA", "product_family": "VSM17", "tool_type": "Indexable End Mill", "diameter_mm": 25, "insert_count": 2, "linked_insert_id": insert_ids["insert.widia.xdpt17.wp25pm"], "notes": "Shop shorthand: (25 Tipped)", "confidence": "high", "needs_review": False},
        {"seed_key": "tool.widia.vsm17.32-tipped", "display_name": "32 Tipped", "manufacturer": "WIDIA", "product_family": "VSM17", "tool_type": "Indexable End Mill", "diameter_mm": 32, "insert_count": 3, "linked_insert_id": insert_ids["insert.widia.xdpt17.wp25pm"], "notes": "Shop shorthand: (32 Tipped)", "confidence": "high", "needs_review": False},
        {"seed_key": "tool.round-insert.52-bull", "display_name": "52 Bull", "manufacturer": "", "tool_type": "Round Insert / Bull Cutter", "diameter_mm": 52, "insert_count": 5, "linked_insert_id": insert_ids["insert.zccct.rdkw12.ybg205h"], "notes": "Shop shorthand: (52 Bull)", "confidence": "high", "needs_review": False},
        {"seed_key": "tool.round-insert.66-bull", "display_name": "66 Bull", "manufacturer": "", "tool_type": "Round Insert / Bull Cutter", "diameter_mm": 66, "insert_count": 6, "linked_insert_id": insert_ids["insert.zccct.rdkw12.ybg205h"], "notes": "Shop shorthand: (66 Bull)", "confidence": "high", "needs_review": False},
        {"seed_key": "tool.itc.cupro.8mm-ball", "display_name": "ITC 8mm Cupro Ball Nose", "manufacturer": "ITC", "tool_type": "Ball Nose End Mill", "diameter_mm": 8, "tool_material": "Carbide", "flute_count": 2, "coating": "Cupro (ITC)", "notes": "Cupro is the recorded ITC coating name; no chemistry inferred.", "confidence": "high", "needs_review": False},
        {"seed_key": "tool.widia.40041000t022s.10mm.review", "display_name": "10mm WIDIA 40041000T022S — needs review", "manufacturer": "WIDIA", "manufacturer_part_number": "40041000T022S", "tool_type": "End Mill", "diameter_mm": 10, "confidence": "low", "needs_review": True},
        {"seed_key": "tool.widia.w401m10005szt.10mm.review", "display_name": "10mm WIDIA W401M10005SZT — needs review", "manufacturer": "WIDIA", "model_code": "W401M10005SZT", "tool_type": "End Mill", "diameter_mm": 10, "notes": "Known marking: WU20PE. Exact interpretation is unverified; do not assume it is a coating or tool material.", "confidence": "low", "needs_review": True},
        {"seed_key": "tool.solid-carbide.16mm.4f", "display_name": "16mm Carbide 4-Flute End Mill", "tool_type": "End Mill", "diameter_mm": 16, "tool_material": "Carbide", "flute_count": 4, "confidence": "medium", "needs_review": True, "notes": "Manufacturer and product identity unknown; historical 90 mm stickout is job setup, not tool identity."},
        {"seed_key": "tool.solid-carbide.5mm.3f.altin", "display_name": "5mm Carbide 3-Flute End Mill", "tool_type": "End Mill", "diameter_mm": 5, "tool_material": "Carbide", "flute_count": 3, "coating": "AlTiN", "confidence": "medium", "needs_review": True, "notes": "Manufacturer and product identity unknown."},
        {"seed_key": "tool.solid-carbide.12mm.chamfer.review", "display_name": "12mm Carbide Chamfer Tool — needs review", "tool_type": "Chamfer Mill", "diameter_mm": 12, "tool_material": "Carbide", "confidence": "low", "needs_review": True},
        {"seed_key": "tool.zccct.50mm.45deg.face-mill.review", "display_name": "50mm 45deg Face Mill", "tool_type": "Face Mill", "diameter_mm": 50, "insert_count": 4, "approach_angle_deg": 45, "linked_insert_id": insert_ids["insert.zccct.seht1204afsn.review"], "notes": "Unknown body manufacturer/model. Historical use: soft D2 skin cutting on a Wadkin V8 ISO50; the machine/holder are job history, not inherent tool facts.", "confidence": "low", "needs_review": True},
    )
    for record in tools:
        seed_key = record["seed_key"]
        existing = next((item for item in service.list_tools() if item.get("seed_key") == seed_key), None)
        if existing is None:
            record.setdefault("source_type", "user_supplied")
            known = tuple(
                key for key, value in record.items()
                if key not in {"seed_key", "confidence", "needs_review", "field_provenance", "source_type"}
                and value not in (None, "", [], {})
            )
            record.setdefault("field_provenance", _seed_provenance(known))
            service.add_tool(record)
    itc = next((item for item in service.list_tools() if item.get("seed_key") == "tool.itc.cupro.8mm-ball"), None)
    if itc:
        with database.connect() as connection:
            found = connection.execute(
                "SELECT 1 FROM workshop_observations WHERE tool_id=? AND category='Historical use' LIMIT 1",
                (itc["id"],),
            ).fetchone()
        if found is None:
            service.add_observation(
                itc["id"],
                "Historical use: 60 HRC material, V-pocket finishing, approximately 1 mm stock removal. This is context only, not a standing cutting rule.",
                "Historical use",
            )
    database.set_setting("tool_library_seed_version", "1")


def initialize_tool_library(database) -> None:
    _ddl(database)
    seed_default_library(database)
