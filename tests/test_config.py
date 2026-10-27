import pytest
from pydantic import ValidationError

from app.config import Settings, load_settings


def test_missing_groq_key_allows_offline_mode(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    settings = load_settings()
    assert settings.generation_configured is False
    assert settings.chunk_overlap < settings.chunk_tokens


@pytest.mark.parametrize(
    "overrides",
    [
        {"chunk_overlap": 300},
        {"chunk_overlap": -1},
        {"chunk_tokens": 0},
        {"max_pdf_bytes": 0},
        {"final_k": 21, "candidate_k": 20},
        {"max_pages": 0},
    ],
)
def test_invalid_limits_rejected(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_secret_not_in_settings_or_validation_messages():
    secret = "fake-test-credential-never-use"
    settings = Settings(_env_file=None, groq_api_key=secret, groq_model="test-model")
    assert settings.generation_configured is True
    assert secret not in repr(settings)
    assert secret not in settings.model_dump_json()
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, groq_api_key=secret, chunk_overlap=300)
    assert secret not in str(error.value)


def test_dotenv_and_environment_precedence(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GROQ_MODEL=from-file\nCHUNK_TOKENS=280\n")
    monkeypatch.setenv("GROQ_MODEL", "from-environment")
    assert load_settings().groq_model == "from-environment"
    assert load_settings().chunk_tokens == 280
