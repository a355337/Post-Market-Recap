from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
QUOTE_URL = "https://api.twelvedata.com/quote"


def _redact(value: str, api_key: str) -> str:
    encoded_key = urllib.parse.quote(api_key, safe="")
    return value.replace(api_key, "[REDACTED]").replace(encoded_key, "[REDACTED]")


def _error_message(body: str, api_key: str) -> str:
    try:
        payload: Any = json.loads(body)
    except json.JSONDecodeError:
        return _redact(body, api_key)[:300] or "No error details returned."
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("code")
        if message:
            return _redact(str(message), api_key)[:300]
    return "The API returned an error response."


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Make one Twelve Data quote request to verify the API key."
    )
    parser.add_argument(
        "--symbol",
        default="SPY",
        help="Ticker symbol to test (default: SPY).",
    )
    args = parser.parse_args()
    symbol = args.symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9.^_-]{1,32}", symbol):
        parser.error("symbol may contain only letters, digits, dot, underscore, or hyphen.")

    load_dotenv(BASE_DIR / ".env")
    api_key = os.getenv("TWELVE_DATA_API_KEY", "").strip()
    if not api_key or api_key.lower() == "your_twelve_data_api_key":
        print(
            "TWELVE_DATA_API_KEY 未設定。請在專案 .env 設定 API key，或設定同名環境變數。",
            file=sys.stderr,
        )
        return 2

    query = urllib.parse.urlencode({"symbol": symbol, "apikey": api_key})
    request = urllib.request.Request(
        f"{QUOTE_URL}?{query}",
        headers={"User-Agent": "TaiwanMarketPodcast/1.0", "Accept": "application/json"},
    )
    print(f"Testing Twelve Data quote API for {symbol} (one request)...")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read(4096).decode("utf-8", errors="replace")
        print(f"FAIL: HTTP {error.code}; {_error_message(body, api_key)}")
        return 1
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        print(f"FAIL: Network error ({type(error).__name__}).")
        return 1
    except json.JSONDecodeError:
        print("FAIL: Twelve Data returned invalid JSON.")
        return 1

    if not isinstance(payload, dict):
        print("FAIL: Twelve Data returned an unexpected response.")
        return 1
    if payload.get("status") == "error":
        print(f"FAIL: {_error_message(json.dumps(payload), api_key)}")
        return 1

    price = payload.get("close") or payload.get("price")
    if not price:
        print("FAIL: Response was received but contained no quote price.")
        return 1

    quote_date = payload.get("datetime", "not provided")
    print(f"PASS: {payload.get('symbol', symbol)} close={price}; date={quote_date}")
    if payload.get("change") not in (None, ""):
        print(
            f"Change={payload['change']}; "
            f"percent_change={payload.get('percent_change', 'not provided')}"
        )
    print("API key was not displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
