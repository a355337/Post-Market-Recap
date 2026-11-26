from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from market_podcast_agent.agent import generate_subject_report, root_agent


class AdkWebAgentTests(unittest.TestCase):
    def test_root_agent_is_exported_with_podcast_generation_tools(self) -> None:
        self.assertEqual(root_agent.name, "market_podcast_agent")
        self.assertEqual(
            {tool.__name__ for tool in root_agent.tools},
            {"generate_daily_episode", "generate_subject_report"},
        )

    def test_subject_report_defaults_to_30_minutes(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            report_path = output_dir / "report.mp3"
            with (
                patch("market_podcast_agent.agent.DEFAULT_OUTPUT_DIR", output_dir),
                patch(
                    "market_podcast_agent.agent.build_subject_report",
                    return_value=report_path,
                ) as build_report,
            ):
                result = generate_subject_report("market outlook")

        self.assertEqual(result, {"status": "created", "path": str(report_path)})
        build_report.assert_called_once_with(
            "market outlook",
            output_dir,
            target_minutes=30,
        )


if __name__ == "__main__":
    unittest.main()
