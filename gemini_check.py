from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL = "gemini-4-hydrogen"


def main() -> int:
    load_dotenv(BASE_DIR / ".env")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print(
            "GEMINI_API_KEY 未設定。請在專案 .env 填入 API key，或設定同名環境變數。",
            file=sys.stderr,
        )
        return 2

    model = DEFAULT_MODEL
    client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
    text_ok = False
    print(f"Testing plain text generation with {model}...")
    try:
        response = client.models.generate_content(
            model=model,
            contents="請只回覆：Gemini 文字測試成功",
        )
    except APIError as error:
        print(
            f"FAIL plain text: HTTP {error.code}; status={error.status}; message={error.message}"
        )
    else:
        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            print(f"PASS plain text: {text.strip()}")
            text_ok = True
        else:
            print("FAIL plain text: API returned no text.")

    print("Waiting 2 seconds before the grounding test...")
    time.sleep(2)

    grounding_ok = False
    print(f"Testing Google Search grounding with {model}...")
    try:
        response = client.interactions.create(
            model=model,
            input="請使用 Google 搜尋找一則美股市場消息，並用一句繁體中文摘要。",
            tools=[{"type": "google_search"}],
        )
    except Exception as error:
        print(f"FAIL grounding: {type(error).__name__}: {error}")
    else:
        text = getattr(response, "output_text", None)
        if isinstance(text, str) and text.strip():
            citations = sum(
                1
                for step in (getattr(response, "steps", None) or [])
                for block in (getattr(step, "content", None) or [])
                for annotation in (getattr(block, "annotations", None) or [])
                if getattr(annotation, "type", None) == "url_citation"
            )
            print(f"PASS grounding: citations={citations}")
            grounding_ok = True
        else:
            print("FAIL grounding: API returned no text.")

    print(
        "Result: "
        f"plain_text={'PASS' if text_ok else 'FAIL'}, "
        f"grounding={'PASS' if grounding_ok else 'FAIL'}"
    )
    return 0 if text_ok and grounding_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
