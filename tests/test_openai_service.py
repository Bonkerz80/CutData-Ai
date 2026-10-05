import json
from types import SimpleNamespace

import pytest

from src.cutdata_ai.models.domain import MachiningRequest, MachineProfile
from src.cutdata_ai.models.schema import MACHINING_RESULT_SCHEMA
from src.cutdata_ai.database.database import Database
from src.cutdata_ai.services.openai_service import OpenAIService, OpenAIServiceError, connection_result_for_exception


class FakeResponses:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        payload = {"rpm": 1000, "feed_mm_min": 100, "feed_per_rev_mm": 0.1, "coolant": "Flood coolant", "confidence": "high", "notes": [], "warnings": []}
        return type("Response", (), {"output_text": json.dumps(payload), "id": "resp_test", "usage": {"input_tokens": 20}})()


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()


def test_live_client_has_one_bounded_attempt_per_ai_stage(monkeypatch):
    import openai

    options = {}
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: options.update(kwargs) or FakeClient())
    OpenAIService("test-key")
    assert options["timeout"] == 90.0
    assert options["max_retries"] == 0


def test_ai_timeout_has_clear_non_secret_error():
    class TimedOutResponses:
        def create(self, **kwargs):
            raise TimeoutError("secret transport detail")

    service = OpenAIService("test-key", client=type("Client", (), {"responses": TimedOutResponses()})())
    request = MachiningRequest("Test machine", "Mild Steel", "Drill", "Drilling", {"diameter_mm": 10})
    with pytest.raises(OpenAIServiceError, match="AI research timed out after 90 seconds") as exc:
        service.calculate(request, MachineProfile("Test machine", 10000, 5000))
    assert "secret" not in str(exc.value)


def test_responses_api_uses_strict_json_schema_and_reasoning():
    client = FakeClient()
    service = OpenAIService("test-key", "gpt-6-luna", "medium", client=client)
    request = MachiningRequest("Test machine", "Mild Steel", "Drill", "Drilling", {"diameter_mm": 10})
    machine = MachineProfile("Test machine", 10000, 5000)
    response = service.calculate(request, machine)
    assert response.payload["rpm"] == 1000
    assert response.usage["research_elapsed_seconds"] >= 0
    assert client.responses.kwargs["model"] == "gpt-6-luna"
    assert client.responses.kwargs["reasoning"] == {"effort": "medium"}
    format_spec = client.responses.kwargs["text"]["format"]
    assert format_spec["type"] == "json_schema"
    assert format_spec["strict"] is True
    assert format_spec["schema"] == MACHINING_RESULT_SCHEMA
    instructions = client.responses.kwargs["input"][0]["content"][0]["text"]
    assert "For Drill, make an explicit peck decision" in instructions
    assert "Roughing Waterline for Z-level\n  material-removal roughing" in instructions
    assert "Flat Land Finishing for horizontal flats/lands" in instructions
    assert "true requires a\n  positive Q depth and false requires null" in instructions
    assert "For Reamer, use continuous feed" in instructions
    assert "no drilling cycle/G83" in instructions
    assert "Thread Mill, existing strategy\n  labels remain valid current context" in instructions


@pytest.mark.parametrize(
    ("model", "friendly_name"),
    [
        ("gpt-6-luna", "GPT-6 Luna"),
        ("gpt-6-sol", "GPT-6 Sol"),
        ("gpt-6-astra", "GPT-6 Astra"),
    ],
)
def test_connection_test_retrieves_selected_model_without_creating_response(model, friendly_name):
    class FakeModels:
        def __init__(self):
            self.requested = None

        def retrieve(self, model):
            self.requested = model
            return {"id": model}

    class ConnectionClient:
        def __init__(self):
            self.models = FakeModels()
            self.responses = FakeResponses()

    client = ConnectionClient()
    result = OpenAIService("test-key", model, client=client).test_connection()

    assert result.success is True
    assert result.category == "success"
    assert friendly_name in result.message
    assert client.models.requested == model
    assert client.responses.kwargs is None


def test_connection_test_fallback_is_a_minimal_non_machining_request():
    client = FakeClient()
    result = OpenAIService("test-key", "gpt-6-luna", client=client).test_connection()

    assert result.success is True
    assert client.responses.kwargs["model"] == "gpt-6-luna"
    assert client.responses.kwargs["input"] == "OK"
    assert client.responses.kwargs["max_output_tokens"] == 1


def test_connection_authentication_failure_is_clean():
    class AuthenticationFailure(Exception):
        status_code = 401

    class FailingModels:
        def retrieve(self, model):
            raise AuthenticationFailure("secret-token-must-not-be-shown")

    class ConnectionClient:
        models = FailingModels()

    result = OpenAIService("test-key", "gpt-6-luna", client=ConnectionClient()).test_connection()

    assert result.success is False
    assert result.category == "authentication"
    assert result.message == "Authentication failed\nCheck your OpenAI API key."
    assert "secret-token" not in result.message


@pytest.mark.parametrize("status,category,heading", [
    (400, "request_rejected", "Request rejected"),
    (403, "permission", "Model access denied"),
    (404, "model_unavailable", "Model unavailable"),
    (429, "rate_limit", "Rate limit / quota"),
])
def test_connection_http_failures_are_classified_without_secret_details(status, category, heading):
    class HttpFailure(Exception):
        status_code = status

    result = connection_result_for_exception(HttpFailure("secret-value"), "gpt-6-astra")

    assert result.category == category
    assert result.message.startswith(heading)
    assert "secret-value" not in result.message
    if status in {403, 404}:
        assert "GPT-6 Astra" in result.message
    assert f"HTTP {status}" in result.technical_detail


def test_connection_timeout_is_classified_as_network_without_exception_text():
    result = connection_result_for_exception(TimeoutError("secret-value"), "gpt-6-luna")

    assert result.category == "network"
    assert result.message == "Network error\nUnable to reach OpenAI."
    assert "secret-value" not in result.message


def test_connection_test_does_not_write_to_machining_cache(tmp_path):
    database = Database(tmp_path / "connection.sqlite3")
    client = FakeClient()
    result = OpenAIService("test-key", "gpt-6-luna", client=client).test_connection()

    assert result.success is True
    assert database.recent() == []
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM cache_records").fetchone()[0] == 0


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-6-sol", "gpt-6-astra"])
def test_supported_reasoning_efforts_reach_the_responses_api(model, effort):
    client = FakeClient()
    request = MachiningRequest("Test machine", "Mild Steel", "Drill", "Drilling", {"diameter_mm": 10})
    machine = MachineProfile("Test machine", 10000, 5000)

    OpenAIService("test-key", model, effort, client=client).calculate(request, machine)

    assert client.responses.kwargs["model"] == model
    assert client.responses.kwargs["reasoning"] == {"effort": effort}


def test_guided_request_enables_live_search_and_extracts_sources():
    payload = {"rpm": 1500, "feed_mm_min": 200, "notes": [], "warnings": []}

    class SearchResponses:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                output_text=json.dumps(payload),
                id="guided-response",
                usage={"input_tokens": 20},
                output=[{
                    "type": "web_search_call",
                    "action": {"sources": [{"title": "Manufacturer data", "url": "https://example.com/cutter"}]},
                }],
            )

    responses = SearchResponses()
    request = MachiningRequest(
        "Test machine", "Mild Steel", "Indexable End Mill", "AI Guided",
        {"diameter_mm": 25, "insert_count": 2}, workflow_mode="guided",
    )
    result = OpenAIService("test-key", client=type("Client", (), {"responses": responses})()).calculate(
        request, MachineProfile("Test machine", 10000, 5000)
    )

    assert responses.kwargs["tools"] == [{"type": "web_search", "search_context_size": "high"}]
    assert responses.kwargs["max_tool_calls"] == 4
    assert responses.kwargs["include"] == ["web_search_call.action.sources"]
    assert result.research_status == "searched"
    assert result.research_sources == [{"title": "Manufacturer data", "url": "https://example.com/cutter"}]


def test_guided_search_rejection_retries_without_search_and_marks_unavailable():
    class UnsupportedSearch(Exception):
        status_code = 400

    class FallbackResponses:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise UnsupportedSearch("provider does not support web search")
            return type("Response", (), {
                "output_text": json.dumps({"rpm": 1200, "feed_mm_min": 100, "notes": [], "warnings": []}),
                "id": "fallback-response",
                "usage": {},
                "output": [],
            })()

    responses = FallbackResponses()
    request = MachiningRequest(
        "Test machine", "Mild Steel", "Indexable End Mill", "AI Guided",
        {"diameter_mm": 25, "insert_count": 2}, workflow_mode="guided",
    )
    result = OpenAIService("test-key", client=type("Client", (), {"responses": responses})()).calculate(
        request, MachineProfile("Test machine", 10000, 5000)
    )

    assert len(responses.calls) == 2
    assert "tools" in responses.calls[0]
    assert "tools" not in responses.calls[1]
    assert result.research_status == "unavailable"
    assert result.usage["web_search_error"] == "UnsupportedSearch (HTTP 400)"


def test_verifier_uses_high_reasoning_strict_schema_and_live_search():
    review_payload = {
        "status": "consistent",
        "history_change_assessment": "not_applicable",
        "history_change_reason": "No large changes from nearby history were detected.",
        "summary": "Arithmetic and machine limits check out.",
        "findings": [],
    }

    class ReviewResponses:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                output_text=json.dumps(review_payload),
                id="review-response",
                usage={"output_tokens": 15},
                output=[{
                    "type": "web_search_call",
                    "action": {"sources": [{"title": "Insert catalog", "url": "https://example.com/insert"}]},
                }],
            )

    responses = ReviewResponses()
    service = OpenAIService("test-key", client=type("Client", (), {"responses": responses})())
    result = service.verify(
        MachiningRequest(
            "Test machine", "Mild Steel", "Indexable End Mill", "AI Guided",
            {"diameter_mm": 25, "insert_count": 2}, workflow_mode="guided",
        ),
        MachineProfile("Test machine", 10000, 5000),
        {"rpm": 1500, "feed_mm_min": 210},
        continuity_findings=[],
        validation_corrections=[],
        research_sources=[],
    )

    assert responses.kwargs["reasoning"] == {"effort": "high"}
    assert responses.kwargs["tools"] == [{"type": "web_search", "search_context_size": "high"}]
    assert responses.kwargs["text"]["format"]["strict"] is True
    assert responses.kwargs["text"]["format"]["schema"]["properties"]["status"]["enum"] == [
        "consistent", "review_required", "cannot_verify",
    ]
    assert result.research_status == "searched"
    assert result.research_sources[0]["url"] == "https://example.com/insert"
    assert result.usage["check_elapsed_seconds"] >= 0
