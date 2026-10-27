"""Explicit one-request Groq check. Never run automatically in tests or health checks."""

import json

from groq import APIError, Groq

from app.config import load_settings


def main() -> None:
    settings = load_settings()
    if not settings.generation_configured or not settings.groq_free_confirmed:
        raise SystemExit(
            "Confirm your Groq Free account, then set GROQ_API_KEY, GROQ_MODEL, "
            "and GROQ_FREE_CONFIRMED=true in the ignored .env file."
        )
    try:
        with Groq(
            api_key=settings.groq_api_key.get_secret_value(), max_retries=0, timeout=20,
            default_headers={"User-Agent": "pdf-rag-chatbot/0.1.0"},
        ) as client:
            response = client.chat.completions.with_raw_response.create(
                model=settings.groq_model,
                messages=[{"role": "user", "content": "Reply with the single word READY."}],
                max_completion_tokens=settings.max_output_tokens,
            )
            result = response.parse()
    except APIError as error:
        raise SystemExit(
            f"Groq smoke failed: {type(error).__name__}; HTTP {getattr(error, 'status_code', 'n/a')}. "
            "Check account/model limits locally; no retry or fallback was attempted."
        ) from None
    if not result.choices or not result.choices[0].message.content:
        raise SystemExit("Groq returned no answer content; inspect the model's output/reasoning budget.")
    print(json.dumps({
        "status": "one_request_succeeded",
        "model": result.model,
        "finish_reason": result.choices[0].finish_reason,
        "usage": result.usage.model_dump() if result.usage else None,
        "rate_limit_headers": {
            name: response.headers[name] for name in (
                "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
                "x-ratelimit-reset-requests", "x-ratelimit-limit-tokens",
                "x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens",
            ) if name in response.headers
        },
        "account_plan": "free_status_confirmed_out_of_band",
    }, indent=2))


if __name__ == "__main__":
    main()
