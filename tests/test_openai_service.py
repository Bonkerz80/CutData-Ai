import json

from src.cutdata_ai.models.domain import MachiningRequest, MachineProfile
from src.cutdata_ai.models.schema import MACHINING_RESULT_SCHEMA
from src.cutdata_ai.services.openai_service import OpenAIService


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

