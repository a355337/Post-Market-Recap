from __future__ import annotations

import unittest

from market_podcast_agent.agent import root_agent


class AdkWebAgentTests(unittest.TestCase):
    def test_root_agent_is_exported_with_podcast_generation_tools(self) -> None:
        self.assertEqual(root_agent.name, "market_podcast_agent")
        self.assertEqual(
            {tool.__name__ for tool in root_agent.tools},
            {"generate_daily_episode", "generate_subject_report"},
        )


if __name__ == "__main__":
    unittest.main()
