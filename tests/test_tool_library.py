import sqlite3

from src.cutdata_ai.database.database import Database
from src.cutdata_ai.services.tool_library import ToolLibraryService


def test_seed_records_are_exact_normalized_and_reviewable(tmp_path):
    path = tmp_path / "library.sqlite3"
    database = Database(path)
    library = ToolLibraryService(database)
    tools = {item["display_name"]: item for item in library.list_tools()}
    inserts = {item["display_name"]: item for item in library.list_inserts()}

    assert database.get_setting("tool_library_seed_version") == "1"
    twenty = library.tool_snapshot(tools["20 Tipped"]["id"])
    assert (twenty["diameter_mm"], twenty["insert_count"], twenty["product_family"]) == (20, 2, "VSM11")
    assert (twenty["insert"]["designation"], twenty["insert"]["grade"]) == ("XDPT110408PDSRMM", "WP25PM")
    twenty_five = library.tool_snapshot(tools["25 Tipped"]["id"])
    assert (twenty_five["diameter_mm"], twenty_five["insert_count"], twenty_five["product_family"]) == (25, 2, "VSM17")
    assert (twenty_five["insert"]["designation"], twenty_five["insert"]["grade"]) == ("XDPT170408PESRMM", "WP25PM")
    thirty_two = library.tool_snapshot(tools["32 Tipped"]["id"])
    assert (thirty_two["diameter_mm"], thirty_two["insert_count"], thirty_two["insert"]["grade"]) == (32, 3, "WP25PM")

    for name, diameter, count in (("52 Bull", 52, 5), ("66 Bull", 66, 6)):
        snapshot = library.tool_snapshot(tools[name]["id"])
        assert (snapshot["diameter_mm"], snapshot["insert_count"]) == (diameter, count)
        assert (snapshot["insert"]["designation"], snapshot["insert"]["grade"]) == ("RDKW12T3MO-1", "YBG205H")

    itc = tools["ITC 8mm Cupro Ball Nose"]
    assert (itc["diameter_mm"], itc["flute_count"], itc["tool_material"], itc["coating"]) == (8, 2, "Carbide", "Cupro (ITC)")
    assert itc["linked_insert_id"] is None
    assert len(library.observations_for_tool(itc["id"])) == 1
    assert "not a standing cutting rule" in library.observations_for_tool(itc["id"])[0]["note"]

    assert inserts["WIDIA XDPT11 WP25PM"]["manufacturer_part_number"] == "5415319"
    assert inserts["WIDIA XDPT17 WP25PM"]["manufacturer_part_number"] == "5987949"
    assert inserts["WIDIA XDPT17 WP25PM"]["coating"] == ""
    assert inserts["ZCC RDKW12 YBG205H"]["coating"] == ""
    assert inserts["ZCC-CT SEHT1204AFSN — needs review"]["needs_review"] is True
    for name in (
        "10mm WIDIA 40041000T022S — needs review",
        "10mm WIDIA W401M10005SZT — needs review",
        "16mm Carbide 4-Flute End Mill",
        "5mm Carbide 3-Flute End Mill",
        "12mm Carbide Chamfer Tool — needs review",
        "50mm 45deg Face Mill",
    ):
        assert tools[name]["needs_review"] is True
    unknown_marking = tools["10mm WIDIA W401M10005SZT — needs review"]
    assert unknown_marking["coating"] == ""
    assert "WU20PE" in unknown_marking["notes"]
    assert tools["16mm Carbide 4-Flute End Mill"]["default_stickout_mm"] is None

    with database.connect() as connection:
        tables = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"tool_library", "tool_inserts", "workshop_observations", "saved_tools"} <= tables


def test_insert_tool_crud_relationship_revisions_and_delete_handling(tmp_path):
    library = ToolLibraryService(Database(tmp_path / "crud.sqlite3"))
    insert = library.add_insert({
        "display_name": "Example insert", "manufacturer": "Maker", "designation": "EX10",
        "grade": "G1", "corner_radius_mm": 0.4,
    })
    tool = library.add_tool({
        "display_name": "Example cutter", "tool_type": "Indexable End Mill",
        "diameter_mm": 16, "insert_count": 3, "linked_insert_id": insert["id"],
    })
    assert library.tool_snapshot(tool["id"])["insert"]["designation"] == "EX10"
    assert tool["revision"] == 1

    changed_insert = library.update_insert(insert["id"], {"grade": "G2"})
    assert changed_insert["revision"] == 2
    assert changed_insert["user_modified"] is True
    assert changed_insert["field_provenance"]["grade"]["status"] == "user_supplied"
    changed_tool = library.update_tool(tool["id"], {"diameter_mm": 18})
    assert (changed_tool["diameter_mm"], changed_tool["revision"], changed_tool["user_modified"]) == (18, 2, True)

    duplicate = library.duplicate_tool(tool["id"])
    assert duplicate["linked_insert_id"] == insert["id"]
    assert duplicate["seed_key"] is None
    assert duplicate["user_modified"] is True
    duplicate_insert = library.duplicate_insert(insert["id"])
    assert duplicate_insert["seed_key"] is None

    library.delete_insert(insert["id"])
    after_delete = library.get_tool(tool["id"])
    assert after_delete["linked_insert_id"] is None
    assert after_delete["needs_review"] is True
    assert after_delete["revision"] == 3
    assert library.get_insert(insert["id"]) is None

    library.delete_tool(duplicate["id"])
    assert library.get_tool(duplicate["id"]) is None


def test_seed_migration_is_idempotent_and_never_resets_user_edits(tmp_path):
    path = tmp_path / "seed.sqlite3"
    database = Database(path)
    library = ToolLibraryService(database)
    tool = next(item for item in library.list_tools() if item["display_name"] == "25 Tipped")
    library.update_tool(tool["id"], {"diameter_mm": 27, "notes": "User-adjusted body measurement"})
    reopened = Database(path)
    library_after = ToolLibraryService(reopened)
    same = next(item for item in library_after.list_tools() if item["seed_key"] == "tool.widia.vsm17.25-tipped")
    assert same["diameter_mm"] == 27
    assert same["notes"] == "User-adjusted body measurement"
    assert same["user_modified"] is True
    assert same["revision"] == 2
    assert len(library_after.list_tools()) == 12
    assert len(library_after.list_inserts()) == 4


def test_snapshots_and_observations_are_independent_of_later_library_edits(tmp_path):
    library = ToolLibraryService(Database(tmp_path / "history.sqlite3"))
    tool = next(item for item in library.list_tools() if item["display_name"] == "25 Tipped")
    before = library.tool_snapshot(tool["id"])
    observation_id = library.add_observation(
        tool["id"], "Ran perfect", "Good result", actual_rpm=2100, actual_feed_mm_min=620,
    )
    assert library.observations_for_tool(tool["id"])[0]["actual_feed_mm_min"] == 620
    library.update_observation(observation_id, "A little noisy", "Too noisy", actual_doc_mm=4)
    assert library.observations_for_tool(tool["id"])[0]["user_modified"] is True
    library.update_insert(before["insert"]["library_id"], {"grade": "WP-new"})
    library.update_tool(tool["id"], {"diameter_mm": 26})
    after = library.tool_snapshot(tool["id"])
    assert before["diameter_mm"] == 25
    assert before["insert"]["grade"] == "WP25PM"
    assert after["diameter_mm"] == 26
    assert after["insert"]["grade"] == "WP-new"
    library.delete_observation(observation_id)
    assert library.observations_for_tool(tool["id"]) == []


def test_legacy_saved_tools_table_is_preserved(tmp_path):
    path = tmp_path / "old-tools.sqlite3"
    database = Database(path)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO saved_tools(name,tool_type,tool_json,created_at,last_used_at,use_count) VALUES(?,?,?,?,?,?)",
            ("Old compatibility row", "End Mill", "{}", "created", "used", 3),
        )
    Database(path)
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT name,tool_json,use_count FROM saved_tools").fetchone()
    assert row == ("Old compatibility row", "{}", 3)

