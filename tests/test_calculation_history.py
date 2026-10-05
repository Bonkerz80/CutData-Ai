import json
from dataclasses import replace

from src.cutdata_ai.database.database import Database
from src.cutdata_ai.models.domain import MachiningRequest, MachineProfile
from src.cutdata_ai.services.calculation_history import (
    related_calculation_history,
    small_depth_change_findings,
)
from src.cutdata_ai.services.calculation_service import CalculationService
from src.cutdata_ai.services.normalization import (
    model_cache_identity,
    normalize_request,
    request_hash,
)
from src.cutdata_ai.services.openai_service import OpenAIServiceError, ServiceResponse, VerificationResponse


MACHINE = MachineProfile("HAAS VF-2", 10000, 8000, rigidity="medium")
TOOL_SNAPSHOT = {
    "manufacturer": "Example Tools",
    "model": "25 Tipped",
    "tool_type": "Indexable End Mill",
    "diameter_mm": 25,
    "insert_count": 2,
    "insert": {"designation": "XDPT170408PESRMM", "grade": "WP25PM"},
}


def _request(depth: float, *, hardness: float | None = None) -> MachiningRequest:
    return MachiningRequest(
        machine=MACHINE.name,
        material="Mild Steel",
        tool_type="Indexable End Mill",
        operation="AI Guided",
        parameters={
            "diameter_mm": 25,
            "insert_count": 2,
            "job_type": "Profile / outside contour",
            "job_depth_mm": depth,
            "material_thickness_mm": depth,
            "stock_on_side_mm": 3,
        },
        hardness_hrc=hardness,
        workflow_mode="guided",
        tool_snapshot=TOOL_SNAPSHOT,
    )


def _result(rpm: float, speed: float, doc: float) -> dict:
    return {
        "rpm": rpm,
        "cutting_speed_m_min": speed,
        "feed_mm_min": rpm * 2 * 0.07,
        "feed_per_tooth_mm": 0.07,
        "axial_doc_mm": doc,
        "radial_doc_mm": 3,
        "stepover_mm": 3,
        "recommended_pass_count": 16,
        "recommended_operation": "Roughing Waterline",
        "recommended_strategy": "Rough in axial passes",
        "confidence": "medium",
        "warnings": [],
    }


def _save(database: Database, request: MachiningRequest, result: dict) -> None:
    normalized = normalize_request(request)
    database.add_recent(request_hash(normalized), normalized, result, "ai", model="gpt-6-luna")


def test_history_matches_same_tool_setup_and_selects_nearest_distinct_depth(tmp_path):
    database = Database(tmp_path / "history.sqlite3")
    _save(database, _request(61.5), _result(1900, 149.2, 4))
    _save(database, _request(62.5), _result(1500, 117.8, 3))

    history = related_calculation_history(database, _request(62))

    assert len(history) == 2
    assert {row["depth_mm"] for row in history} == {61.5, 62.5}
    assert all("not confirmed by an operator" in row["source_status"] for row in history)
    assert history[0]["depth_mm"] == 62.5  # Most recently saved of equally close entries.
    assert history[0]["result"]["rpm"] == 1500


def test_history_rejects_mild_steel_entry_with_contradictory_hrc_value(tmp_path):
    database = Database(tmp_path / "hardness-history.sqlite3")
    _save(database, _request(61.5, hardness=60), _result(350, 27.5, 4))

    # Even if a malformed/legacy caller presents the same bad hardness input,
    # it cannot reinforce its own contradictory historic recommendation.
    assert related_calculation_history(database, _request(62, hardness=60)) == []


def test_small_depth_change_with_material_speed_jump_is_flagged_for_review(tmp_path):
    database = Database(tmp_path / "continuity.sqlite3")
    _save(database, _request(61.5), _result(1900, 149.2, 4))
    request = _request(62)
    request = replace(request, comparison_history=related_calculation_history(database, request))

    findings = small_depth_change_findings(request, _result(1500, 117.8, 3))

    assert len(findings) == 1
    assert "0.5 mm" in findings[0]
    assert "RPM" in findings[0]
    assert "cutting speed" in findings[0]
    assert "axial DOC" in findings[0]


def test_history_does_not_mix_tool_identity_or_manual_calculations(tmp_path):
    database = Database(tmp_path / "identity-history.sqlite3")
    other_tool = dict(TOOL_SNAPSHOT, model="Different cutter")
    other_request = MachiningRequest(**{**_request(61.5).__dict__, "tool_snapshot": other_tool})
    _save(database, other_request, _result(1900, 149.2, 4))
    manual = MachiningRequest(**{**_request(63).__dict__, "workflow_mode": "manual"})
    _save(database, manual, _result(1900, 149.2, 4))

    assert related_calculation_history(database, _request(62)) == []


def test_history_context_invalidates_model_cache_but_not_physical_request_identity():
    request = _request(62)
    normalized_without_history = normalize_request(request)
    normalized_with_history = normalize_request(
        replace(request, comparison_history=[{"depth_mm": 61.5, "result": {"rpm": 1900}}])
    )

    assert request_hash(normalized_without_history) == request_hash(normalized_with_history)
    assert model_cache_identity(normalized_without_history, "gpt-6-luna") != model_cache_identity(
        normalized_with_history, "gpt-6-luna"
    )


def test_guided_calculation_cross_checks_history_and_requires_review_on_unjustified_jump(tmp_path):
    database = Database(tmp_path / "guided-review.sqlite3")
    _save(database, _request(61.5), _result(1900, 149.2, 4))

    class ReviewingAI:
        is_mock = False
        model = "gpt-6-luna"

        def __init__(self):
            self.calculation_request = None
            self.review_args = None

        def calculate(self, request, machine):
            self.calculation_request = request
            payload = {
                "rpm": 1500,
                "cutting_speed_m_min": 117.8,
                "feed_mm_min": 210,
                "feed_per_tooth_mm": 0.07,
                "axial_doc_mm": 3,
                "radial_doc_mm": 3,
                "stepover_mm": 3,
                "recommended_operation": "Roughing Waterline",
                "recommended_strategy": "Rough in axial passes",
                "recommended_pass_count": 21,
                "pass_plan": [{
                    "stage": "Rough",
                    "passes": 21,
                    "operation": "Roughing Waterline",
                    "axial_doc_mm": 3,
                    "radial_engagement_mm": 3,
                    "stepover_mm": 3,
                    "stock_to_leave_mm": 0.3,
                    "rpm": 1500,
                    "feed_mm_min": 210,
                    "notes": "",
                }],
                "confidence": "high",
                "notes": [],
                "warnings": [],
            }
            return ServiceResponse(
                payload,
                json.dumps(payload),
                "primary prompt",
                self.model,
                response_id="primary-id",
                usage={"input_tokens": 100, "output_tokens": 50},
                research_status="searched",
                research_sources=[{"title": "Toolmaker data", "url": "https://example.com/tool"}],
            )

        def verify(self, request, machine, candidate_result, **kwargs):
            self.review_args = kwargs
            return VerificationResponse(
                payload={
                    "status": "consistent",
                    "history_change_assessment": "justified",
                    # A bare "justified" label without an explanation must
                    # not turn a significant depth-adjacent jump green.
                    "history_change_reason": "",
                    "summary": "The RPM reduction has no supporting reason.",
                    "findings": ["Explain why RPM changed for a 0.5 mm depth change."],
                },
                raw_text="review response",
                prompt="review prompt",
                response_id="review-id",
                usage={"input_tokens": 70, "output_tokens": 20},
                research_status="searched",
                research_sources=[{"title": "Insert manufacturer", "url": "https://example.com/insert"}],
            )

    ai = ReviewingAI()
    outcome = CalculationService(database, ai).calculate(_request(62), MACHINE)

    assert len(ai.calculation_request.comparison_history) == 1
    assert ai.review_args["continuity_findings"]
    assert ai.review_args["research_sources"][0]["url"] == "https://example.com/tool"
    assert outcome.result.verification_status == "review_required"
    assert outcome.result.confidence == "low"
    assert len(outcome.result.research_sources) == 2
    assert "RPM reduction" in outcome.result.verification_summary
    assert any("operator review" in warning for warning in outcome.result.warnings)
    assert not any("History change rationale:" in item for item in outcome.result.verification_findings)
    assert outcome.result.verification_response_id == "review-id"
    assert outcome.verification_prompt == "review prompt"
    assert outcome.verification_raw_response == "review response"
    assert outcome.usage["input_tokens"] == 170
    assert outcome.usage["output_tokens"] == 70


def test_failed_independent_check_is_persisted_as_incomplete_without_leaking_error_text(tmp_path):
    class BrokenReviewer:
        is_mock = False
        model = "gpt-6-luna"

        def calculate(self, request, machine):
            payload = {
                "rpm": 1000,
                "feed_mm_min": 100,
                "feed_per_tooth_mm": 0.05,
                "recommended_operation": "Roughing Waterline",
                "recommended_strategy": "Rough in axial passes",
                "recommended_pass_count": 1,
                "pass_plan": [{"stage": "Rough", "passes": 1}],
                "notes": [],
                "warnings": [],
            }
            return ServiceResponse(
                payload,
                json.dumps(payload),
                "primary prompt",
                self.model,
                research_status="no_sources",
            )

        def verify(self, *args, **kwargs):
            raise RuntimeError("sensitive request detail")

    outcome = CalculationService(
        Database(tmp_path / "failed-review.sqlite3"),
        BrokenReviewer(),
    ).calculate(_request(62), MACHINE)

    assert outcome.result.verification_status == "check_incomplete"
    assert outcome.result.confidence == "low"
    assert "RuntimeError" in outcome.result.verification_summary
    assert "sensitive request detail" not in outcome.result.verification_summary
    assert any("No current web-search source" in warning for warning in outcome.result.warnings)

    class TimedOutReviewer(BrokenReviewer):
        def verify(self, *args, **kwargs):
            raise OpenAIServiceError("Independent check timed out after 90 seconds.")

    timed_out = CalculationService(
        Database(tmp_path / "timed-out-review.sqlite3"),
        TimedOutReviewer(),
    ).calculate(_request(62), MACHINE)
    assert timed_out.result.verification_status == "check_incomplete"
    assert timed_out.result.confidence == "low"
    assert "(timeout)" in timed_out.result.verification_summary


def test_incomplete_independent_check_is_not_cached_and_is_retried(tmp_path):
    class FlakyReviewer:
        is_mock = False
        model = "gpt-6-luna"
        calculate_calls = 0
        fail_review = True

        def calculate(self, request, machine):
            self.calculate_calls += 1
            payload = {
                "rpm": 1000,
                "feed_mm_min": 100,
                "feed_per_tooth_mm": 0.05,
                "recommended_operation": "Roughing Waterline",
                "recommended_strategy": "Rough in axial passes",
                "recommended_pass_count": 1,
                "pass_plan": [{"stage": "Rough", "passes": 1}],
                "notes": [],
                "warnings": [],
            }
            return ServiceResponse(payload, json.dumps(payload), "primary prompt", self.model)

        def verify(self, *args, **kwargs):
            if self.fail_review:
                raise OpenAIServiceError("Independent check timed out after 90 seconds.")
            report = {
                "status": "consistent",
                "history_change_assessment": "not_applicable",
                "history_change_reason": "No nearby history.",
                "summary": "Consistent.",
                "findings": [],
            }
            return VerificationResponse(report, json.dumps(report), "review prompt")

    database = Database(tmp_path / "retry-review.sqlite3")
    service = FlakyReviewer()
    first = CalculationService(database, service).calculate(_request(62), MACHINE)
    assert first.result.verification_status == "check_incomplete"

    service.fail_review = False
    second = CalculationService(database, service).calculate(_request(62), MACHINE)
    assert service.calculate_calls == 2
    assert second.cache_hit is False
    assert second.result.verification_status == "cross_checked"

    third = CalculationService(database, service).calculate(_request(62), MACHINE)
    assert service.calculate_calls == 2
    assert third.cache_hit is True


def test_legacy_cached_incomplete_check_is_ignored(tmp_path):
    database = Database(tmp_path / "legacy-incomplete.sqlite3")
    request = _request(62)
    normalized = normalize_request(request)
    plan = [{"stage": "Rough", "passes": 16}]
    stale = dict(_result(1000, 78.5, 4), pass_plan=plan, verification_status="check_incomplete")
    database.put_cache_record(
        request_hash=model_cache_identity(normalized, "gpt-6-luna"),
        normalized_request=normalized,
        returned_data=stale,
        validated_data=stale,
        model="gpt-6-luna",
        response_id="",
        usage={},
    )

    class Reviewer:
        is_mock = False
        model = "gpt-6-luna"
        calculate_calls = 0

        def calculate(self, request, machine):
            self.calculate_calls += 1
            payload = dict(_result(1000, 78.5, 4), pass_plan=plan)
            return ServiceResponse(payload, json.dumps(payload), "primary prompt", self.model)

    service = Reviewer()
    outcome = CalculationService(database, service).calculate(request, MACHINE)
    assert service.calculate_calls == 1
    assert outcome.cache_hit is False


def test_quick_guided_result_skips_the_check_and_checked_mode_reruns_it(tmp_path):
    class Reviewer:
        is_mock = False
        model = "gpt-6-luna"
        calculate_calls = 0
        verify_calls = 0

        def calculate(self, request, machine):
            self.calculate_calls += 1
            payload = dict(_result(1000, 78.5, 4), pass_plan=[{"stage": "Rough", "passes": 16}])
            return ServiceResponse(payload, json.dumps(payload), "primary prompt", self.model)

        def verify(self, *args, **kwargs):
            self.verify_calls += 1
            report = {
                "status": "consistent",
                "history_change_assessment": "not_applicable",
                "history_change_reason": "No nearby history.",
                "summary": "Consistent.",
                "findings": [],
            }
            return VerificationResponse(report, json.dumps(report), "review prompt")

    database = Database(tmp_path / "quick.sqlite3")
    service = Reviewer()
    quick = CalculationService(database, service, independent_check=False).calculate(_request(62), MACHINE)
    assert service.verify_calls == 0
    assert quick.result.verification_status == "not_run"
    assert quick.result.confidence != "low"
    assert any("Quick calculation" in warning for warning in quick.result.warnings)

    # A repeat quick request is served from the cache.
    again = CalculationService(database, service, independent_check=False).calculate(_request(62), MACHINE)
    assert again.cache_hit is True and service.calculate_calls == 1

    # Asking for the check never accepts the unchecked cached result.
    checked = CalculationService(database, service).calculate(_request(62), MACHINE)
    assert checked.cache_hit is False
    assert service.verify_calls == 1
    assert checked.result.verification_status == "cross_checked"

    # A quick request can reuse the better, checked result.
    reuse = CalculationService(database, service, independent_check=False).calculate(_request(62), MACHINE)
    assert reuse.cache_hit is True
    assert reuse.result.verification_status == "cross_checked"
