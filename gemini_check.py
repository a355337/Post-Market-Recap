from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError


BASE_DIR = Path(__file__).resolve().parent
MODEL = "gemini-3.1-flash-lite"


def main() -> int:
    load_dotenv(BASE_DIR / ".env")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print(
            "GEMINI_API_KEY 未設定。請在專案 .env 填入 API key，或設定同名環境變數。",
            file=sys.stderr,
        )
        return 2

    client = genai.Client(api_key=api_key)
    print(f"Testing text generation with {MODEL}...")
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents="請只回覆：Gemini 文字測試成功",
        )
    except APIError as error:
        print(
            f"FAIL: HTTP {error.code}; "
            f"status={error.status}; message={error.message}"
        )
        return 1

    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        print("FAIL: API returned no text.")
        return 1

    print(f"PASS: {text.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
