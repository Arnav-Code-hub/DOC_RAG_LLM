import json

import httpx
import pytest
from groq import Groq

from app.config import Settings
from scripts.smoke_groq import main


@pytest.mark.parametrize(
    "overrides",
    [
        {"groq_api_key": None, "groq_model": "test", "groq_free_confirmed": True},
        {"groq_api_key": "fake-private-key", "groq_model": "test", "groq_free_confirmed": False},
    ],
)
def test_smoke_refuses_unconfigured_or_unconfirmed_account(monkeypatch, overrides):
    monkeypatch.setattr("scripts.smoke_groq.load_settings", lambda: Settings(_env_file=None, **overrides))
    with pytest.raises(SystemExit) as error:
        main()
    assert "Free account" in str(error.value)
    assert "fake-private-key" not in str(error.value)


def test_smoke_makes_one_capped_request_and_reports_only_safe_metadata(monkeypatch, capsys):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "test-completion", "object": "chat.completion", "created": 0,
            "model": "test-model",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "READY"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        }, headers={
            "x-ratelimit-limit-requests": "1000",
            "x-ratelimit-limit-tokens": "8000",
            "authorization": "fake-private-key",
        })

    settings = Settings(_env_file=None, groq_api_key="fake-private-key", groq_model="test-model",
                        groq_free_confirmed=True, max_output_tokens=300)
    monkeypatch.setattr("scripts.smoke_groq.load_settings", lambda: settings)
    monkeypatch.setattr("scripts.smoke_groq.Groq", lambda **kwargs: Groq(
        **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond))))

    main()

    assert len(requests) == 1
    assert requests[0].headers["user-agent"] == "pdf-rag-chatbot/0.1.0"
    assert json.loads(requests[0].content)["max_completion_tokens"] == 300
    output = capsys.readouterr().out
    assert "fake-private-key" not in output
    report = json.loads(output)
    assert report["status"] == "one_request_succeeded"
    assert report["usage"]["total_tokens"] == 15
    assert report["finish_reason"] == "stop"
    assert report["rate_limit_headers"] == {
        "x-ratelimit-limit-requests": "1000", "x-ratelimit-limit-tokens": "8000",
    }
