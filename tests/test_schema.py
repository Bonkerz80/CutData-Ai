from src.cutdata_ai.models.schema import MACHINING_RESULT_SCHEMA, result_from_dict


def test_schema_requires_optional_ai_context_fields_and_limits_setup_risk():
    required = MACHINING_RESULT_SCHEMA["required"]
    for field_name in (
        "estimated_spindle_power_kw",
        "estimated_spindle_torque_nm",
        "engagement_description",
        "setup_risk",
        "recommendation_summary",
    ):
        assert field_name in required
    assert MACHINING_RESULT_SCHEMA["properties"]["setup_risk"]["enum"] == ["low", "medium", "high", None]


def test_optional_ai_context_fields_are_converted_without_becoming_local_judgement():
    result = result_from_dict(
        {
            "rpm": 1000,
            "feed_mm_min": 100,
            "estimated_spindle_power_kw": 5,
            "estimated_spindle_torque_nm": None,
            "engagement_description": "Light radial engagement",
            "setup_risk": "medium",
            "recommendation_summary": "Start conservatively and verify the first cut.",
            "coolant": "Flood coolant",
            "confidence": "high",
            "notes": [],
            "warnings": [],
        }
    )

    assert result.estimated_spindle_power_kw == 5
    assert result.estimated_spindle_torque_nm is None
    assert result.engagement_description == "Light radial engagement"
    assert result.setup_risk == "medium"
    assert result.recommendation_summary.startswith("Start conservatively")
