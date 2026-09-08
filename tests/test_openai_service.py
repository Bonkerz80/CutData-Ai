import json

import pytest

from src.cutdata_ai.models.domain import MachiningRequest, MachineProfile
from src.cutdata_ai.models.schema import MACHINING_RESULT_SCHEMA
from src.cutdata_ai.database.database import Database
from src.cutdata_ai.services.openai_service import OpenAIService, connection_result_for_exception


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


def test_responses_api_uses_strict_json_schema_and_reasoning():
    client = FakeClient()
    service = OpenAIService("test-key", "gpt-5.6-luna", "medium", client=client)
    request = MachiningRequest("Test machine", "Mild Steel", "Drill", "Drilling", {"diameter_mm": 10})
    machine = MachineProfile("Test machine", 10000, 5000)
    response = service.calculate(request, machine)
    assert response.payload["rpm"] == 1000
    assert client.responses.kwargs["model"] == "gpt-5.6-luna"
    assert client.responses.kwargs["reasoning"] == {"effort": "medium"}
    format_spec = client.responses.kwargs["text"]["format"]
    assert format_spec["type"] == "json_schema"
    assert format_spec["strict"] is True
    assert format_spec["schema"] == MACHINING_RESULT_SCHEMA
    instructions = client.responses.kwargs["input"][0]["content"][0]["text"]
    assert "peck_recommended must be true or false, never null" in instructions
    assert "Roughing\n  Waterline is Z-level/material-removal roughing" in instructions
    assert "Flat\n  Land Finishing is for horizontal flats or lands" in instructions
    assert "positive finite Q increment" in instructions
    assert "peck_mm MUST be null" in instructions
    assert "Never return a Q value with a false no-peck decision" in instructions
    assert "recommended_cycle" in instructions
    assert "For every Reamer request" in instructions
    assert "peck_recommended to false" in instructions
    assert "never request a\n  drilling-style peck" in instructions
    assert "drilling-family" not in instructions


def test_connection_test_retrieves_selected_model_without_creating_response():
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
    result = OpenAIService("test-key", "gpt-5.6-luna", client=client).test_connection()

    assert result.success is True
    assert result.category == "success"
    assert "GPT-5.6 Luna" in result.message
    assert client.models.requested == "gpt-5.6-luna"
    assert client.responses.kwargs is None


def test_connection_test_fallback_is_a_minimal_non_machining_request():
    client = FakeClient()
    result = OpenAIService("test-key", "gpt-5.6-luna", client=client).test_connection()

    assert result.success is True
    assert client.responses.kwargs["model"] == "gpt-5.6-luna"
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

    result = OpenAIService("test-key", "gpt-5.6-luna", client=ConnectionClient()).test_connection()

    assert result.success is False
    assert result.category == "authentication"
    assert result.message == "Authentication failed\nCheck your OpenAI API key."
    assert "secret-token" not in result.message


@pytest.mark.parametrize("status,category,heading", [
    (400, "request_rejected", "Request rejected"),
    (403, "permission", "Permission denied"),
    (404, "model_unavailable", "Model unavailable"),
    (429, "rate_limit", "Rate limit / quota"),
])
def test_connection_http_failures_are_classified_without_secret_details(status, category, heading):
    class HttpFailure(Exception):
        status_code = status

    result = connection_result_for_exception(HttpFailure("secret-value"), "gpt-5.6-luna")

    assert result.category == category
    assert result.message.startswith(heading)
    assert "secret-value" not in result.message
    assert f"HTTP {status}" in result.technical_detail


def test_connection_timeout_is_classified_as_network_without_exception_text():
    result = connection_result_for_exception(TimeoutError("secret-value"), "gpt-5.6-luna")

    assert result.category == "network"
    assert result.message == "Network error\nUnable to reach OpenAI."
    assert "secret-value" not in result.message


def test_connection_test_does_not_write_to_machining_cache(tmp_path):
    database = Database(tmp_path / "connection.sqlite3")
    client = FakeClient()
    result = OpenAIService("test-key", "gpt-5.6-luna", client=client).test_connection()

    assert result.success is True
    assert database.recent() == []
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM cache_records").fetchone()[0] == 0
