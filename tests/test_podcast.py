from __future__ import annotations

import unittest
import base64
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

import holidays

from news_sources import SourceItem
from podcast import (
    TAIPEI,
    build_episode_mp3_path,
    generate_script_section,
    generate_episode_summary,
    generate_spotify_description,
    is_taiwan_workday,
    load_recent_episode_context,
    next_episode_number,
    next_run_at_or_after,
    synthesize_section,
)


class TaiwanWorkdayTests(unittest.TestCase):
    def test_weekends_are_not_workdays(self) -> None:
        self.assertFalse(is_taiwan_workday(date(2026, 11, 21)))
        self.assertFalse(is_taiwan_workday(date(2026, 11, 22)))

    def test_weekday_public_holiday_is_not_a_workday(self) -> None:
        year_holidays = holidays.country_holidays("TW", years=[2026])
        holiday = next(day for day in year_holidays if day.weekday() < 5)
        self.assertFalse(is_taiwan_workday(holiday))

    def test_regular_weekday_is_a_workday(self) -> None:
        year_holidays = holidays.country_holidays("TW", years=[2026])
        day = date(2026, 1, 1)
        while day.weekday() >= 5 or day in year_holidays:
            day += timedelta(days=1)
        self.assertTrue(is_taiwan_workday(day))


class SchedulerTests(unittest.TestCase):
    def test_next_run_uses_taipei_time_and_six_am(self) -> None:
        now = datetime(2026, 11, 20, 5, 0, tzinfo=TAIPEI)
        next_run = next_run_at_or_after(now)
        self.assertEqual(next_run.time(), time(6, 0, tzinfo=TAIPEI))
        self.assertEqual(next_run.date(), now.date())

    def test_next_run_moves_to_future_on_or_after_six(self) -> None:
        now = datetime(2026, 11, 20, 6, 1, tzinfo=TAIPEI)
        next_run = next_run_at_or_after(now)
        self.assertGreaterEqual(next_run, now)
        self.assertEqual(next_run.hour, 6)
        self.assertEqual(next_run.minute, 0)

    def test_naive_datetime_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            next_run_at_or_after(datetime(2026, 11, 20, 5, 0))


class ScriptGenerationTests(unittest.TestCase):
    def test_prompt_requests_two_host_dialogue_format(self) -> None:
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            text="主持人甲：市場回顧。[S01]\n主持人乙：接下來看利率。[S01]"
        )
        source = SourceItem(
            source_id="S01",
            category="news",
            source_name="Example News",
            title="Market update",
            url="https://example.com/market",
            published="2026-11-23",
            summary="Markets moved.",
        )

        generate_script_section(
            client,
            date(2026, 11, 23),
            1,
            "開場",
            "市場",
            [source],
        )

        prompt = client.models.generate_content.call_args.kwargs["contents"]
        self.assertIn("雙主持人對話格式", prompt)
        self.assertIn("主持人甲：台詞", prompt)
        self.assertIn("主持人乙：台詞", prompt)

    def test_recent_episode_context_is_included_as_nonfactual_context(self) -> None:
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            text="市場消息摘要。[S01]"
        )
        source = SourceItem(
            source_id="S01",
            category="news",
            source_name="Example News",
            title="Market update",
            url="https://example.com/market",
            published="2026-11-23",
            summary="Markets moved.",
        )

        generate_script_section(
            client,
            date(2026, 11, 23),
            1,
            "開場",
            "市場",
            [source],
            "【前集逐字稿：2026-11-20】\n前集內容",
        )

        prompt = client.models.generate_content.call_args.kwargs["contents"]
        self.assertIn("前集內容", prompt)
        self.assertIn("不得沿用其中的新聞或數字", prompt)
        self.assertIn("下方本段來源再次支持", prompt)

    def test_loads_only_latest_prior_transcripts(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "美股財經Podcast_20261118.txt").write_text(
                "較早逐字稿", encoding="utf-8"
            )
            (output_dir / "美股財經Podcast_20261120.txt").write_text(
                "最近逐字稿", encoding="utf-8"
            )
            (output_dir / "美股財經Podcast_20261123.txt").write_text(
                "當日逐字稿", encoding="utf-8"
            )
            (output_dir / "其他逐字稿.txt").write_text("不相關", encoding="utf-8")

            context = load_recent_episode_context(
                output_dir, date(2026, 11, 23)
            )

        self.assertIn("最近逐字稿", context)
        self.assertIn("較早逐字稿", context)
        self.assertNotIn("當日逐字稿", context)
        self.assertNotIn("不相關", context)

    def test_prompt_limits_greeting_and_signoff_to_episode_edges(self) -> None:
        source = SourceItem(
            source_id="S01",
            category="news",
            source_name="Example News",
            title="Market update",
            url="https://example.com/market",
            published="2026-11-20",
            summary="Markets moved.",
        )

        for section_number, expected, unexpected in (
            (1, "全集唯一的開場", "全集唯一的結尾"),
            (5, "同一集節目中間的連續段落", "全集唯一的開場"),
            (10, "全集唯一的結尾", "同一集節目中間的連續段落"),
        ):
            with self.subTest(section_number=section_number):
                client = Mock()
                client.models.generate_content.return_value = SimpleNamespace(
                    text="市場消息摘要。[S01]"
                )

                generate_script_section(
                    client,
                    date(2026, 11, 20),
                    section_number,
                    "單元",
                    "市場",
                    [source],
                )

                prompt = client.models.generate_content.call_args.kwargs["contents"]
                self.assertIn(expected, prompt)
                self.assertNotIn(unexpected, prompt)

    def test_generates_from_supplied_sources_without_search_grounding(self) -> None:
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            text="市場消息摘要。[S01]"
        )
        source = SourceItem(
            source_id="S01",
            category="news",
            source_name="Example News",
            title="Market update",
            url="https://example.com/market",
            published="2026-11-20",
            summary="Markets moved.",
        )

        text, cited_sources = generate_script_section(
            client,
            date(2026, 11, 20),
            1,
            "開場",
            "市場",
            [source],
        )

        self.assertEqual(text, "市場消息摘要。[S01]")
        self.assertEqual(cited_sources, {"S01"})
        client.interactions.create.assert_not_called()
        prompt = client.models.generate_content.call_args.kwargs["contents"]
        self.assertIn("https://example.com/market", prompt)
        self.assertNotIn("google_search", prompt)

    def test_rejects_unknown_source_marker(self) -> None:
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            text="未確認消息。[S99]"
        )
        source = SourceItem(
            source_id="S01",
            category="news",
            source_name="Example News",
            title="Market update",
            url="https://example.com/market",
            published="2026-11-20",
            summary="Markets moved.",
        )

        with self.assertRaisesRegex(RuntimeError, "unknown source IDs"):
            generate_script_section(
                client,
                date(2026, 11, 20),
                1,
                "開場",
                "市場",
                [source],
            )


class PodcastSynthesisTests(unittest.TestCase):
    def test_uses_multi_speaker_config_and_fixed_host_voice_ids(self) -> None:
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_audio=SimpleNamespace(data=base64.b64encode(b"audio").decode())
        )

        result = synthesize_section(
            client,
            "主持人甲：市場今天震盪。\n主持人乙：我們接著看原因。",
        )

        self.assertEqual(result, b"audio")
        call = client.interactions.create.call_args.kwargs
        self.assertEqual(call["model"], "gemini-3.8-flash-tts")
        speech_config = call["generation_config"]["speech_config"]
        speaker_configs = speech_config["multi_speaker_voice_config"]["speaker_voice_configs"]
        self.assertEqual(
            [item["speaker"] for item in speaker_configs],
            ["主持人甲", "主持人乙"],
        )
        self.assertEqual(
            [item["voice_config"]["prebuilt_voice_config"]["voice_name"] for item in speaker_configs],
            ["Kore", "Puck"],
        )


class EpisodeNamingTests(unittest.TestCase):
    def test_summary_is_trimmed_and_limited_to_eight_characters(self) -> None:
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            text="「科技股震盪」\n"
        )

        summary = generate_episode_summary(client, ["逐字稿內容"])

        self.assertEqual(summary, "科技股震盪")

    def test_summary_longer_than_eight_characters_is_rejected(self) -> None:
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            text="科技股震盪市場觀望"
        )

        with self.assertRaisesRegex(RuntimeError, "1-8 characters"):
            generate_episode_summary(client, ["逐字稿內容"])

    def test_spotify_description_is_trimmed_and_limited_to_100_characters(self) -> None:
        description = "本集聚焦科技股走勢與聯準會利率政策。" * 2
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            text=f"「{description}」\n"
        )

        result = generate_spotify_description(client, ["逐字稿內容"])

        self.assertEqual(result, description)
        self.assertLessEqual(len(result), 100)

    def test_spotify_description_over_100_characters_is_trimmed(self) -> None:
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            text="美股市場焦點" * 20
        )

        result = generate_spotify_description(client, ["逐字稿內容"])

        self.assertEqual(len(result), 100)
        self.assertTrue(result.endswith("…"))

    def test_spotify_description_trims_at_a_sentence_boundary_when_possible(self) -> None:
        sentence = "本集聚焦科技股與市場走勢" * 4 + "。"
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            text=sentence + "這是多餘的延伸內容" * 15 + "。"
        )

        result = generate_spotify_description(client, ["逐字稿內容"])

        self.assertEqual(result, sentence)
        self.assertLessEqual(len(result), 100)

    def test_episode_number_increments_from_existing_mp3s(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "美股盤後EP2｜科技股震盪.mp3").touch()
            (output_dir / "美股盤後EP7｜利率觀望.mp3").touch()
            (output_dir / "美股財經Podcast_20261120.mp3").touch()

            self.assertEqual(next_episode_number(output_dir), 8)

    def test_mp3_path_uses_windows_safe_fullwidth_separator(self) -> None:
        path = build_episode_mp3_path(Path("output"), 3, "科技股震盪")

        self.assertEqual(path.name, "美股盤後EP3｜科技股震盪.mp3")
        self.assertNotIn("|", path.name)


if __name__ == "__main__":
    unittest.main()
