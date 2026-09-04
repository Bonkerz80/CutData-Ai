from src.cutdata_ai.services.derived_values import (
    axial_doc_ratio,
    hole_ld_ratio,
    material_removal_rate_cm3_min,
    radial_engagement_percent,
    torque_from_power,
    usage_percent,
)


def test_display_only_derived_values_use_metric_relationships():
    assert hole_ld_ratio(50, 10) == 5
    assert radial_engagement_percent(2.5, 10) == 25
    assert axial_doc_ratio(3, 10) == 0.3
    assert material_removal_rate_cm3_min(2, 5, 1000) == 10
    assert usage_percent(6000, 12000) == 50
    assert torque_from_power(5, 1000) == 47.75


def test_display_only_derived_values_return_none_when_inputs_are_unavailable():
    assert hole_ld_ratio(50, 0) is None
    assert radial_engagement_percent(None, 10) is None
    assert axial_doc_ratio(-1, 10) is None
    assert material_removal_rate_cm3_min(2, 5, 0) is None
    assert usage_percent(12000, None) is None
    assert torque_from_power(5, 0) is None
