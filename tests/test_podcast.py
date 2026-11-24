from __future__ import annotations

import base64
import io
import time as time_module
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import holidays

from news_sources import SourceItem
from podcast import (
    TAIPEI,
    _parse_args,
    _create_client,
    _generate_content,
    _run_with_progress_logging,
    AdkTextModel,
    build_episode_mp3_path,
    create_episode,
    create_subject_report,
    generate_subject_report,
    generate_script_section,
    generate_episode_summary,
    generate_spotify_description,
    is_taiwan_workday,
    load_recent_episode_context,
    next_episode_number,
    next_subject_report_number,
    next_run_at_or_after,
    _probe_mp3_duration,
    synthesize_section,
    confirm_gemini_settings,
)


class AdkClientTests(unittest.TestCase):
    def test_confirm_gemini_settings_waits_for_enter(self) -> None:
        with (
            patch("builtins.input", return_value="") as input_mock,
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            confirm_gemini_settings()

        input_mock.assert_called_once()
        self.assertIn(
            "文字模型（Google ADK Agent）：gemini-3.5-flash-lite",
            output.getvalue(),
        )
        self.assertIn("TTS 模型：gemini-3.8-flash-tts", output.getvalue())
        self.assertIn(
            "主持人 Voice ID：voice_x3oo1ycwy9ne",
            output.getvalue(),
        )

    def test_confirm_gemini_settings_cancels_on_other_input(self) -> None:
        with (
            patch("builtins.input", return_value="取消"),
            patch("sys.stdout", new_callable=io.StringIO),
            self.assertRaisesRegex(SystemExit, "已取消啟動"),
        ):
            confirm_gemini_settings()

    def test_logs_adk_request_start_and_completion(self) -> None:
        client = Mock()
        client.text_model.generate_content.return_value = SimpleNamespace(text="ok")

        with self.assertLogs("market_podcast", level="INFO") as captured:
            response = _generate_content(client, "script section 6", "prompt")

        self.assertEqual(response.text, "ok")
        self.assertTrue(
            any(
                "Google ADK request started: script section 6" in line
                for line in captured.output
            )
        )
        self.assertTrue(
            any(
                "Google ADK request completed: script section 6" in line
                for line in captured.output
            )
        )

    def test_logs_traceback_when_adk_request_is_interrupted(self) -> None:
        client = Mock()
        client.text_model.generate_content.side_effect = KeyboardInterrupt

        with self.assertLogs("market_podcast", level="ERROR") as captured:
            with self.assertRaises(KeyboardInterrupt):
                _generate_content(client, "script section 6", "prompt")

        self.assertTrue(
            any(
                "Google ADK request interrupted: script section 6" in line
                for line in captured.output
            )
        )

    def test_logs_progress_while_a_request_is_waiting(self) -> None:
        with (
            patch("podcast.GEMINI_PROGRESS_INTERVAL", 0.01),
            self.assertLogs("market_podcast", level="INFO") as captured,
        ):
            _run_with_progress_logging(
                "Gemini test request", lambda: time_module.sleep(0.03)
            )

        self.assertTrue(
            any(
                "Gemini test request still in progress" in line
                for line in captured.output
            )
        )

    def test_configures_bounded_exponential_retries_for_retryable_errors(self) -> None:
        with (
            patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}),
            patch("podcast.genai.Client") as client_factory,
        ):
            client = _create_client()

        client_factory.assert_called_once_with(
            api_key="test-key",
            http_options={
                "api_version": "v1beta",
                "retry_options": {
                    "attempts": 5,
                    "initial_delay": 1.0,
                    "max_delay": 60.0,
                    "exp_base": 2.0,
                    "jitter": 1.0,
                    "http_status_codes": [429, 503],
                },
            },
        )
        self.assertEqual(client.text_model.api_key, "test-key")
        self.assertIs(client.audio_client, client_factory.return_value)

    def test_adk_agent_uses_configured_model_key_and_returns_final_text(self) -> None:
        final_event = SimpleNamespace(
            is_final_response=lambda: True,
            content=SimpleNamespace(
                parts=[SimpleNamespace(text="  播客內容  "), SimpleNamespace(text=None)]
            ),
        )
        with patch("podcast.Runner") as runner_factory:
            runner_factory.return_value.run.return_value = [final_event]

            response = AdkTextModel("test-key").generate_content(
                model="gemini-test",
                contents="請撰寫內容",
            )

        self.assertEqual(response.text, "播客內容")
        agent = runner_factory.call_args.kwargs["agent"]
        self.assertEqual(agent.name, "market_podcast_writer")
        self.assertEqual(agent.model.model, "gemini-test")
        self.assertEqual(agent.model.client_kwargs["api_key"], "test-key")
        self.assertEqual(agent.model.retry_options.attempts, 5)
        self.assertEqual(agent.model.retry_options.http_status_codes, [429, 503])
        self.assertEqual(
            agent.model.client_kwargs["http_options"]["api_version"],
            "v1beta",
        )
        self.assertEqual(
            runner_factory.return_value.run.call_args.kwargs["new_message"].parts[0].text,
            "請撰寫內容",
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
    def test_prompt_requests_one_host_monologue_format(self) -> None:
        client = Mock()
        client.text_model.generate_content.return_value = SimpleNamespace(
            text="市場回顧。[S01]\n接下來看利率。[S01]"
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

        prompt = client.text_model.generate_content.call_args.kwargs["contents"]
        self.assertIn("單一主持人獨白格式", prompt)
        self.assertIn("陳知衡", prompt)
        self.assertIn("沉穩、理性", prompt)

    def test_recent_episode_context_is_included_as_nonfactual_context(self) -> None:
        client = Mock()
        client.text_model.generate_content.return_value = SimpleNamespace(
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

        prompt = client.text_model.generate_content.call_args.kwargs["contents"]
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
                client.text_model.generate_content.return_value = SimpleNamespace(
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

                prompt = client.text_model.generate_content.call_args.kwargs["contents"]
                self.assertIn(expected, prompt)
                self.assertNotIn(unexpected, prompt)

    def test_generates_from_supplied_sources_without_search_grounding(self) -> None:
        client = Mock()
        client.text_model.generate_content.return_value = SimpleNamespace(
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
        prompt = client.text_model.generate_content.call_args.kwargs["contents"]
        self.assertIn("https://example.com/market", prompt)
        self.assertNotIn("google_search", prompt)

    def test_retries_once_when_response_has_no_source_citations(self) -> None:
        client = Mock()
        client.text_model.generate_content.side_effect = [
            SimpleNamespace(text="市場消息摘要。"),
            SimpleNamespace(text="市場消息摘要。[S01]"),
        ]
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
            3,
            "市場",
            "市場消息",
            [source],
        )

        self.assertEqual(text, "市場消息摘要。[S01]")
        self.assertEqual(cited_sources, {"S01"})
        self.assertEqual(client.text_model.generate_content.call_count, 2)
        retry_prompt = client.text_model.generate_content.call_args.kwargs["contents"]
        self.assertIn("上一版草稿沒有任何來源標記", retry_prompt)
        self.assertIn("市場消息摘要。", retry_prompt)

    def test_still_rejects_response_without_citations_after_bounded_retries(self) -> None:
        client = Mock()
        client.text_model.generate_content.side_effect = [
            SimpleNamespace(text="市場消息摘要。"),
            SimpleNamespace(text="修訂後仍沒有標記。"),
            SimpleNamespace(text="第二次修訂仍沒有標記。"),
            SimpleNamespace(text="第三次修訂仍沒有標記。"),
        ]
        source = SourceItem(
            source_id="S01",
            category="news",
            source_name="Example News",
            title="Market update",
            url="https://example.com/market",
            published="2026-11-20",
            summary="Markets moved.",
        )

        with self.assertRaisesRegex(RuntimeError, "no source citations"):
            generate_script_section(
                client,
                date(2026, 11, 20),
                3,
                "市場",
                "市場消息",
                [source],
            )

        self.assertEqual(client.text_model.generate_content.call_count, 4)

    def test_retries_once_when_response_cites_unknown_source(self) -> None:
        client = Mock()
        client.text_model.generate_content.side_effect = [
            SimpleNamespace(text="市場消息摘要。[S17]"),
            SimpleNamespace(text="市場消息摘要。[S01]"),
        ]
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
            3,
            "市場",
            "市場消息",
            [source],
        )

        self.assertEqual(text, "市場消息摘要。[S01]")
        self.assertEqual(cited_sources, {"S01"})
        self.assertEqual(client.text_model.generate_content.call_count, 2)
        retry_prompt = client.text_model.generate_content.call_args.kwargs["contents"]
        self.assertIn("[S17]", retry_prompt)
        self.assertIn("只能使用本提示列出的來源 ID", retry_prompt)

    def test_rejects_unknown_source_marker(self) -> None:
        client = Mock()
        client.text_model.generate_content.side_effect = [
            SimpleNamespace(text="未確認消息。[S99]"),
            SimpleNamespace(text="修訂後仍引用無效來源。[S98]"),
            SimpleNamespace(text="第二次修訂仍引用無效來源。[S97]"),
            SimpleNamespace(text="第三次修訂仍引用無效來源。[S96]"),
        ]
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

        self.assertEqual(client.text_model.generate_content.call_count, 4)


class EpisodeCacheTests(unittest.TestCase):
    def test_reuses_cached_script_after_tts_failure(self) -> None:
        episode_date = date(2026, 11, 23)
        source = SourceItem(
            source_id="S01",
            category="news",
            source_name="Example News",
            title="Market update",
            url="https://example.com/market",
            published="2026-11-23",
            summary="Markets moved.",
        )

        def create_mp3(_audio_chunks: list[bytes], output_path: Path) -> float:
            self.assertEqual(len(_audio_chunks), 2)
            output_path.write_bytes(b"mp3")
            return 60.0

        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            with (
                patch("podcast._create_client", return_value=Mock()),
                patch(
                    "podcast.EPISODE_SECTIONS",
                    (
                        ("開場", "市場概況"),
                        ("利率", "總體經濟"),
                        ("企業", "財報"),
                        ("結尾", "重點回顧"),
                    ),
                ),
                patch(
                    "podcast.collect_sources",
                    return_value=([source], []),
                ) as collect_sources,
                patch("podcast.select_sources", return_value=[source]),
                patch(
                    "podcast.generate_script_section",
                    return_value=("主持人甲：市場走勢。[S01]", {"S01"}),
                ) as generate_script,
                patch("podcast.generate_episode_summary", return_value="市場"),
                patch("podcast.generate_spotify_description", return_value="市場說明"),
                patch(
                    "podcast.synthesize_section",
                    side_effect=[RuntimeError("TTS failed"), b"audio-1", b"audio-2"],
                ) as synthesize,
                patch("podcast.convert_wav_chunks_to_mp3", side_effect=create_mp3),
            ):
                with self.assertLogs("market_podcast", level="ERROR"):
                    with self.assertRaisesRegex(RuntimeError, "TTS failed"):
                        create_episode(episode_date, output_dir)

                cache_path = output_dir / "美股財經Podcast_20261123_cache.json"
                self.assertTrue(cache_path.is_file())
                transcript_path = output_dir / "美股財經Podcast_20261123.txt"
                self.assertIn(
                    "市場走勢。[S01]",
                    transcript_path.read_text(encoding="utf-8"),
                )

                mp3_path = create_episode(episode_date, output_dir)

            collect_sources.assert_called_once()
            self.assertEqual(
                collect_sources.call_args.kwargs["sec_user_agent"],
                "TaiwanMarketPodcast/1.0 (a355337@gmail.com)",
            )
            self.assertEqual(generate_script.call_count, 4)
            self.assertEqual(synthesize.call_count, 3)
            self.assertTrue(mp3_path.is_file())
            self.assertFalse(cache_path.exists())
            self.assertTrue(transcript_path.is_file())


class SubjectReportTests(unittest.TestCase):
    def test_retries_subject_report_until_repaired_response_has_citations(self) -> None:
        client = Mock()
        client.text_model.generate_content.side_effect = [
            SimpleNamespace(text="初稿內容"),
            SimpleNamespace(text="第一次修訂仍無來源標記。"),
            SimpleNamespace(text="第二次修訂內容 [S01]"),
        ]
        source = SourceItem(
            source_id="S01",
            category="news",
            source_name="CNBC",
            title="Computing industry outlook",
            url="https://example.com/computing",
            published="2026-11-23",
            summary="A report about computing.",
        )

        report, cited_source_ids = generate_subject_report(
            client,
            "quantum computing",
            date(2026, 11, 23),
            [source],
        )

        self.assertEqual(report, "第二次修訂內容 [S01]")
        self.assertEqual(cited_source_ids, {"S01"})
        self.assertEqual(client.text_model.generate_content.call_count, 3)
        second_repair_prompt = client.text_model.generate_content.call_args_list[2].kwargs[
            "contents"
        ]
        self.assertIn("上一版草稿沒有任何來源標記", second_repair_prompt)
        self.assertIn("第一次修訂仍無來源標記。", second_repair_prompt)

    def test_repairs_subject_report_without_source_citations(self) -> None:
        client = Mock()
        client.text_model.generate_content.side_effect = [
            SimpleNamespace(text="初稿內容"),
            SimpleNamespace(text="修訂內容 [S01]"),
        ]
        source = SourceItem(
            source_id="S01",
            category="news",
            source_name="CNBC",
            title="Computing industry outlook",
            url="https://example.com/computing",
            published="2026-11-23",
            summary="A report about computing.",
        )

        report, cited_source_ids = generate_subject_report(
            client,
            "quantum computing",
            date(2026, 11, 23),
            [source],
            12,
        )

        self.assertEqual(report, "修訂內容 [S01]")
        self.assertEqual(cited_source_ids, {"S01"})
        self.assertEqual(client.text_model.generate_content.call_count, 2)
        prompt = client.text_model.generate_content.call_args_list[0].kwargs["contents"]
        self.assertIn("quantum computing", prompt)
        self.assertIn("依語意判斷", prompt)
        self.assertIn("約 12 分鐘", prompt)
        self.assertIn("4128 至 4560 個中文字", prompt)
        repair_prompt = client.text_model.generate_content.call_args_list[1].kwargs[
            "contents"
        ]
        self.assertIn("維持原稿篇幅", repair_prompt)

    def test_stops_when_no_sources_are_relevant_to_the_subject(self) -> None:
        client = Mock()
        client.text_model.generate_content.return_value = SimpleNamespace(
            text="目前收集到的資料沒有與主題直接相關的來源。"
        )
        source = SourceItem(
            source_id="S01",
            category="news",
            source_name="CNBC",
            title="Computing industry outlook",
            url="https://example.com/computing",
            published="2026-11-23",
            summary="A report about computing.",
        )

        with self.assertRaisesRegex(RuntimeError, "No collected sources are relevant"):
            generate_subject_report(
                client,
                "ocean exploration",
                date(2026, 11, 23),
                [source],
            )

        client.text_model.generate_content.assert_called_once()

    def test_subject_option_parses_without_daily_mode(self) -> None:
        with patch(
            "sys.argv",
            ["podcast.py", "--subject", "黃仁勳", "--minute", "10"],
        ):
            args = _parse_args()

        self.assertEqual(args.subject, "黃仁勳")
        self.assertEqual(args.target_minutes, 10)
        self.assertIsNone(args.mode)

    def test_report_synthesizes_with_existing_tts_and_writes_outputs(self) -> None:
        relevant = SourceItem(
            source_id="S01",
            category="news",
            source_name="CNBC",
            title="Computing industry outlook",
            url="https://example.com/computing",
            published="2026-11-23",
            summary="A report about computing.",
        )
        unrelated = SourceItem(
            source_id="S02",
            category="economics",
            source_name="BLS",
            title="Employment report",
            url="https://example.com/jobs",
            published="2026-11-23",
            summary="Employment data.",
        )

        def create_mp3(audio_chunks: list[bytes], output_path: Path) -> float:
            self.assertEqual(audio_chunks, [b"wav"])
            output_path.write_bytes(b"mp3")
            return 60.0

        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            client = Mock()
            with (
                patch("podcast._create_client", return_value=client),
                patch(
                    "podcast.collect_sources",
                    return_value=([relevant, unrelated], []),
                ),
                patch(
                    "podcast.generate_subject_report",
                    return_value=("分析內容 [S01]", {"S01"}),
                ) as generate_report,
                patch("podcast.synthesize_section", return_value=b"wav") as synthesize,
                patch("podcast.convert_wav_chunks_to_mp3", side_effect=create_mp3),
            ):
                mp3_path = create_subject_report("量子運算", output_dir)

            self.assertTrue(mp3_path.name.startswith("主題報告EP1｜量子運算｜"))
            self.assertTrue(mp3_path.is_file())
            transcript = mp3_path.with_suffix(".txt").read_text(encoding="utf-8")
            self.assertIn("分析內容 [S01]", transcript)
            self.assertIn("主題報告｜量子運算｜", transcript)
            tts_transcript = mp3_path.with_name(
                f"{mp3_path.stem}_TTS逐字稿.txt"
            ).read_text(encoding="utf-8")
            self.assertEqual(tts_transcript, "分析內容\n")
            self.assertNotIn("[S01]", tts_transcript)
            duration_report = mp3_path.with_name(
                f"{mp3_path.stem}_時長分析.txt"
            ).read_text(encoding="utf-8")
            self.assertIn("指定時長：10 分鐘", duration_report)
            self.assertIn("實際 MP3 時長：1.00 分鐘（60.0 秒）", duration_report)
            self.assertIn("送入 TTS 的逐字稿字數（不含空白）：4", duration_report)
            self.assertIn("本次實測語速：4.0 字／分鐘", duration_report)
            self.assertIn("下次目標字數：約 40 字", duration_report)
            source_list = mp3_path.with_name(
                f"{mp3_path.stem}_sources.txt"
            ).read_text(encoding="utf-8")
            self.assertIn("Computing industry outlook", source_list)
            self.assertNotIn("Employment report", source_list)
            generate_report.assert_called_once()
            self.assertEqual(generate_report.call_args.args[4], 10)
            synthesize.assert_called_once()
            self.assertEqual(
                synthesize.call_args.args[1],
                "分析內容",
            )
            generate_report.assert_called_once()
            self.assertEqual(generate_report.call_args.args[1], "量子運算")
            self.assertEqual(
                generate_report.call_args.args[3],
                [relevant, unrelated],
            )


class PodcastSynthesisTests(unittest.TestCase):
    def test_mp3_duration_is_read_from_ffmpeg_metadata(self) -> None:
        completed = SimpleNamespace(
            stderr=(
                b"ffmpeg metadata with a non-UTF8 byte \x8a\n"
                b"Duration: 00:02:03.45, start: 0.0"
            )
        )
        with (
            patch("podcast.imageio_ffmpeg.get_ffmpeg_exe", return_value="ffmpeg"),
            patch("podcast.subprocess.run", return_value=completed) as run,
        ):
            duration = _probe_mp3_duration(Path("output.mp3"))

        self.assertEqual(duration, 123.45)
        self.assertEqual(run.call_args.args[0][-1], "output.mp3")

    def test_uses_single_speaker_config_and_fixed_host_voice_id(self) -> None:
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_audio=SimpleNamespace(data=base64.b64encode(b"audio").decode())
        )

        with self.assertLogs("market_podcast", level="INFO") as captured:
            result = synthesize_section(
                client,
                "主持人甲：市場今天震盪。\n主持人乙：我們接著看原因。",
            )

        self.assertEqual(result, b"audio")
        self.assertTrue(
            any(
                "TTS request starting: model=gemini-3.8-flash-tts"
                in line
                and "host_voice=voice_x3oo1ycwy9ne" in line
                for line in captured.output
            )
        )
        call = client.interactions.create.call_args.kwargs
        self.assertEqual(call["model"], "gemini-3.8-flash-tts")
        speech_config = call["generation_config"]["speech_config"]
        self.assertEqual(
            speech_config,
            [{"voice": "voice_x3oo1ycwy9ne"}],
        )
        input_text = call["input"][0]["content"][0]["text"]
        self.assertEqual(
            input_text,
            "市場今天震盪。\n我們接著看原因。",
        )
        speech_metadata = call["input"][0]["content"][0]["annotations"][0]
        self.assertEqual(speech_metadata["type"], "speech_metadata")
        self.assertIn("沉穩", speech_metadata["style"])

    def test_logs_fixed_tts_settings_before_request(self) -> None:
        client = Mock()
        client.interactions.create.return_value = SimpleNamespace(
            output_audio=SimpleNamespace(data=base64.b64encode(b"audio").decode())
        )

        with self.assertLogs("market_podcast", level="INFO") as captured:
            synthesize_section(client, "主持人甲：測試。\n主持人乙：確認。")

        self.assertTrue(
            any(
                "TTS request starting: model=gemini-3.8-flash-tts"
                in line
                and "host_voice=voice_x3oo1ycwy9ne" in line
                for line in captured.output
            )
        )
        self.assertEqual(
            client.interactions.create.call_args.kwargs["model"],
            "gemini-3.8-flash-tts",
        )


class EpisodeNamingTests(unittest.TestCase):
    def test_summary_is_trimmed(self) -> None:
        client = Mock()
        client.text_model.generate_content.return_value = SimpleNamespace(
            text="「科技股震盪」\n"
        )

        summary = generate_episode_summary(client, ["逐字稿內容"])

        self.assertEqual(summary, "科技股震盪")

    def test_long_summary_warns_and_is_trimmed_to_100_characters(self) -> None:
        client = Mock()
        client.text_model.generate_content.return_value = SimpleNamespace(
            text="科技股震盪市場觀望" * 20
        )

        with self.assertLogs("market_podcast", level="WARNING") as logs:
            summary = generate_episode_summary(client, ["逐字稿內容"])

        self.assertEqual(len(summary), 100)
        self.assertIn("exceeded 100 characters", logs.output[0])
        path = build_episode_mp3_path(Path("output"), 3, summary)
        self.assertLessEqual(len(summary), 100)
        self.assertEqual(path.suffix, ".mp3")

    def test_spotify_description_is_trimmed_and_limited_to_1000_characters(self) -> None:
        description = "本集聚焦科技股走勢與聯準會利率政策。" * 2
        client = Mock()
        client.text_model.generate_content.return_value = SimpleNamespace(
            text=f"「{description}」\n"
        )

        result = generate_spotify_description(client, ["逐字稿內容"])

        self.assertEqual(result, description)
        self.assertLessEqual(len(result), 1000)

    def test_spotify_description_over_1000_characters_is_trimmed(self) -> None:
        client = Mock()
        client.text_model.generate_content.return_value = SimpleNamespace(
            text="美股市場焦點" * 200
        )

        result = generate_spotify_description(client, ["逐字稿內容"])

        self.assertEqual(len(result), 1000)
        self.assertTrue(result.endswith("…"))

    def test_spotify_description_trims_at_a_sentence_boundary_when_possible(self) -> None:
        sentence = "本集聚焦科技股與市場走勢" * 4 + "。"
        client = Mock()
        client.text_model.generate_content.return_value = SimpleNamespace(
            text=sentence + "這是多餘的延伸內容" * 150
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

    def test_subject_report_number_increments_for_same_subject(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "主題報告EP2｜量子運算｜20261120.mp3").touch()
            (output_dir / "主題報告｜量子運算｜20261119.mp3").touch()
            (output_dir / "主題報告EP5｜其他主題｜20261120.mp3").touch()

            self.assertEqual(
                next_subject_report_number(output_dir, "量子運算"),
                3,
            )

    def test_mp3_path_uses_windows_safe_fullwidth_separator(self) -> None:
        path = build_episode_mp3_path(Path("output"), 3, "科技股震盪")

        self.assertEqual(path.name, "美股盤後EP3｜科技股震盪.mp3")
        self.assertNotIn("|", path.name)


if __name__ == "__main__":
    unittest.main()
