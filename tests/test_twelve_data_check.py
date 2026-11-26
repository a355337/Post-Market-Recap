from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from twelve_data_check import _error_message, main


class TwelveDataCheckTests(unittest.TestCase):
    def test_error_message_redacts_api_key(self) -> None:
        message = _error_message(
            json.dumps({"message": "Invalid key: secret-key"}), "secret-key"
        )

        self.assertNotIn("secret-key", message)
        self.assertIn("[REDACTED]", message)

    def test_successful_check_makes_one_request_without_printing_key(self) -> None:
        api_key = "private-test-key"
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            {
                "symbol": "SPY",
                "close": "650.00",
                "change": "1.25",
                "percent_change": "0.19",
                "datetime": "2026-11-20",
            }
        ).encode()
        output = io.StringIO()

        with (
            patch.dict(os.environ, {"TWELVE_DATA_API_KEY": api_key}, clear=True),
            patch("twelve_data_check.load_dotenv"),
            patch("twelve_data_check.urllib.request.urlopen", return_value=response) as urlopen,
            patch.object(sys, "argv", ["twelve_data_check.py"]),
            contextlib.redirect_stdout(output),
        ):
            result = main()

        self.assertEqual(result, 0)
        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("PASS: SPY close=650.00", output.getvalue())
        self.assertNotIn(api_key, output.getvalue())

    def test_http_error_does_not_expose_api_key(self) -> None:
        api_key = "private-test-key"
        body = json.dumps({"message": f"Invalid API key {api_key}"}).encode()
        error = urllib.error.HTTPError(
            "https://api.twelvedata.com/quote",
            401,
            "Unauthorized",
            None,
            io.BytesIO(body),
        )
        output = io.StringIO()

        with (
            patch.dict(os.environ, {"TWELVE_DATA_API_KEY": api_key}, clear=True),
            patch("twelve_data_check.load_dotenv"),
            patch("twelve_data_check.urllib.request.urlopen", side_effect=error),
            patch.object(sys, "argv", ["twelve_data_check.py"]),
            contextlib.redirect_stdout(output),
        ):
            result = main()

        self.assertEqual(result, 1)
        self.assertIn("HTTP 401", output.getvalue())
        self.assertNotIn(api_key, output.getvalue())


if __name__ == "__main__":
    unittest.main()
