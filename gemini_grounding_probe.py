from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai


BASE_DIR = Path(__file__).resolve().parent
MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-4-hydrogen",
)


def _citation_count(response: Any) -> int:
    return sum(
        1
        for step in (getattr(response, "steps", None) or [])
        for block in (getattr(step, "content", None) or [])
        for annotation in (getattr(block, "annotations", None) or [])
        if getattr(annotation, "type", None) == "url_citation"
    )


def _error_details(error: Exception) -> tuple[str, str, bool]:
    code = getattr(error, "code", None)
    message = str(getattr(error, "message", None) or error)
    details = f"HTTP/status={code}; {message}"
    lowered = f"{code} {message}".lower()
    is_quota_error = (
        code == 429
        or "429" in lowered
        or "quota" in lowered
        or "rate limit" in lowered
        or "too_many_requests" in lowered
    )
    return type(error).__name__, details, is_quota_error


def probe_models(
    client: Any,
    models: tuple[str, ...],
    delay_seconds: float,
    continue_on_quota: bool,
) -> tuple[list[str], bool]:
    working_models: list[str] = []
    quota_limited = False

    for index, model in enumerate(models):
        if index:
            time.sleep(delay_seconds)

        print(f"Testing {model}...")
        try:
            response = client.interactions.create(
                model=model,
                input=(
                    "請使用 Google 搜尋找一則美股市場消息，"
                    "用一句繁體中文摘要，並提供來源。"
                ),
                tools=[{"type": "google_search"}],
            )
        except Exception as error:
            error_type, details, is_quota_error = _error_details(error)
            print(f"FAIL {model}: {error_type}: {details}")
            if is_quota_error:
                quota_limited = True
                if not continue_on_quota:
                    print(
                        "Stopping: quota/rate-limit errors usually affect the "
                        "project, so other model results would be inconclusive. "
                        "Use --continue-on-quota to try them anyway."
                    )
                    break
            continue

        text = getattr(response, "output_text", None)
        citations = _citation_count(response)
        if isinstance(text, str) and text.strip() and citations > 0:
            print(f"PASS {model}: citations={citations}")
            working_models.append(model)
        else:
            print(f"FAIL {model}: no text or grounded citations (citations={citations})")

    return working_models, quota_limited


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe Gemini 3+ models for Google Search grounding access."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds between model requests (default: 2).",
    )
    parser.add_argument(
        "--continue-on-quota",
        action="store_true",
        help="Continue testing after a 429/quota error; this may issue more billable searches.",
    )
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay must be non-negative.")

    load_dotenv(BASE_DIR / ".env")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print(
            "GEMINI_API_KEY 未設定。請在專案 .env 填入 API key，或設定同名環境變數。",
            file=sys.stderr,
        )
        return 2

    client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
    working_models, quota_limited = probe_models(
        client,
        MODELS,
        args.delay,
        args.continue_on_quota,
    )
    if working_models:
        print("Grounding passed: " + ", ".join(working_models))
        return 0
    if quota_limited:
        print("No model confirmed: resolve the project quota/rate limit, then rerun.")
        return 2
    print("No model returned grounded citations.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
