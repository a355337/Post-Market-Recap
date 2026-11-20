from __future__ import annotations

import argparse
import base64
import io
import logging
import os
import subprocess
import tempfile
import time
import wave
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import holidays
from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError
import imageio_ffmpeg


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = BASE_DIR / "output"
TAIPEI = ZoneInfo("Asia/Taipei")
EPISODE_SECTIONS = (
    ("開場與隔夜市場", "最新美股交易日、主要指數、整體市場情緒與重要變化。"),
    ("利率與總體經濟", "美國公債殖利率、通膨、就業與近期重要經濟數據。"),
    ("聯準會觀察", "聯準會官員談話、利率預期及其對市場的可能影響。"),
    ("大型科技與 AI", "大型科技股、半導體與人工智慧產業的重要消息。"),
    ("企業與財報", "最新財報、公司公告、併購或其他值得注意的企業動態。"),
    ("產業與商品", "主要產業輪動，以及美元、原油、黃金等市場變化。"),
    ("市場風險", "市場波動、重要風險及不同觀點；區分已確認事實與推測。"),
    ("台灣投資人焦點", "美股變化對台灣市場、台積電及供應鏈可能帶來的關聯。"),
    ("今日行事曆", "接下來 24 小時的重要經濟數據、財報與市場事件。"),
    ("重點回顧", "整理三個觀察重點，平衡呈現風險，並以非投資建議聲明結尾。"),
)

logger = logging.getLogger("market_podcast")


def is_taiwan_workday(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    taiwan_holidays = holidays.country_holidays("TW", years=[day.year])
    return day not in taiwan_holidays


def next_run_at_or_after(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local_now = now.astimezone(TAIPEI)
    candidate = datetime.combine(local_now.date(), clock_time(6), tzinfo=TAIPEI)
    if candidate < local_now:
        candidate += timedelta(days=1)
    while not is_taiwan_workday(candidate.date()):
        candidate += timedelta(days=1)
    return candidate


def _extract_sources(response: Any) -> list[tuple[str, str]]:
    sources: dict[str, str] = {}
    for step in getattr(response, "steps", None) or []:
        for block in getattr(step, "content", None) or []:
            for annotation in getattr(block, "annotations", None) or []:
                if getattr(annotation, "type", None) != "url_citation":
                    continue
                url = getattr(annotation, "url", None)
                if url:
                    title = getattr(annotation, "title", None) or url
                    sources[url] = title
    return [(title, url) for url, title in sources.items()]


def generate_script_section(
    client: Any, episode_date: date, section_number: int, title: str, topic: str
) -> tuple[str, list[tuple[str, str]]]:
    prompt = f"""請為台灣聽眾撰寫一段美股財經 podcast 口播稿。
節目日期：{episode_date.isoformat()}（台灣時間早上）
本集單元：{section_number}/10「{title}」
本段主題：{topic}

請立即使用 Google Search 搜尋並核對最新資料，先確認截至節目日期可取得的最近一個美股交易日。
僅陳述可由搜尋結果支持的事實；數字要附日期，沒有可靠資料就略過，不可臆測或把預測說成事實。
用自然、清楚的繁體中文口語撰寫約 750 至 900 個中文字，適合一般語速播讀約三分鐘。
避免重複其他單元、投資喊單、保證獲利或未經證實的傳聞。提到重要消息時，請在口播中說出來源機構或媒體名稱。
只輸出可直接朗讀的正文，不要 Markdown、條列符號、網址、製作說明或單元標題。"""

    response = client.interactions.create(
        model=os.getenv("GEMINI_TEXT_MODEL", "gemini-3.1-flash-lite"),
        input=prompt,
        tools=[{"type": "google_search"}],
    )
    text = getattr(response, "output_text", None)
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError(f"Gemini did not return text for section {section_number}.")
    sources = _extract_sources(response)
    if not sources:
        raise RuntimeError(
            f"Gemini returned no verifiable search citations for section {section_number}."
        )
    return text.strip(), sources


def synthesize_section(client: Any, text: str) -> bytes:
    response = client.interactions.create(
        model=os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-lite-tts"),
        input=[
            {
                "type": "user_input",
                "content": [
                    {
                        "type": "text",
                        "text": text,
                        "annotations": [
                            {
                                "type": "speech_metadata",
                                "style": "以自然、清晰、穩定的台灣華語財經 podcast 語氣播讀，正常語速。",
                            }
                        ],
                    }
                ],
            }
        ],
        response_format={"type": "audio"},
        generation_config={
            "speech_config": [{"voice": os.getenv("GEMINI_TTS_VOICE", "Kore")}]
        },
    )
    audio = getattr(getattr(response, "output_audio", None), "data", None)
    if not isinstance(audio, str) or not audio:
        raise RuntimeError("Gemini TTS did not return audio data.")
    return base64.b64decode(audio, validate=True)


def _wave_duration(audio: bytes) -> float:
    with wave.open(io.BytesIO(audio), "rb") as wav_file:
        if wav_file.getcomptype() != "NONE":
            raise ValueError("Gemini returned a compressed WAV stream that cannot be concatenated.")
        if wav_file.getframerate() <= 0:
            raise ValueError("Gemini returned WAV audio with an invalid sample rate.")
        return wav_file.getnframes() / wav_file.getframerate()


def _concat_file_entry(path: Path) -> str:
    escaped_path = str(path.resolve()).replace("\\", "/").replace("'", "'\\''")
    return f"file '{escaped_path}'"


def convert_wav_chunks_to_mp3(chunks: list[bytes], output_path: Path) -> float:
    if not chunks:
        raise ValueError("Cannot create an episode without audio.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_duration = sum(_wave_duration(chunk) for chunk in chunks)
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

    with tempfile.TemporaryDirectory(
        prefix="market_podcast_", dir=output_path.parent
    ) as temporary_directory:
        temporary_path = Path(temporary_directory)
        wav_paths: list[Path] = []
        for index, chunk in enumerate(chunks, start=1):
            wav_path = temporary_path / f"part_{index:02d}.wav"
            wav_path.write_bytes(chunk)
            wav_paths.append(wav_path)

        concat_list = temporary_path / "audio_parts.txt"
        concat_list.write_text(
            "\n".join(_concat_file_entry(path) for path in wav_paths),
            encoding="utf-8",
        )
        temporary_mp3 = temporary_path / output_path.name
        try:
            subprocess.run(
                [
                    ffmpeg_path,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_list),
                    "-vn",
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "128k",
                    "-y",
                    str(temporary_mp3),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as error:
            detail = error.stderr.strip() or "no diagnostic output"
            raise RuntimeError(f"MP3 conversion failed: {detail}") from error
        if not temporary_mp3.is_file() or temporary_mp3.stat().st_size == 0:
            raise RuntimeError("FFmpeg completed without producing an MP3 file.")
        temporary_mp3.replace(output_path)

    return total_duration


def _create_client() -> Any:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is missing. Add it to the .env file or environment."
        )
    return genai.Client(
        api_key=api_key,
        http_options={"api_version": "v1beta"},
    )


def create_episode(episode_date: date, output_dir: Path) -> Path:
    client = _create_client()
    transcript_sections: list[str] = []
    audio_chunks: list[bytes] = []
    all_sources: dict[str, str] = {}

    for section_number, (title, topic) in enumerate(EPISODE_SECTIONS, start=1):
        logger.info("Generating script section %d/%d: %s", section_number, len(EPISODE_SECTIONS), title)
        text, sources = generate_script_section(
            client, episode_date, section_number, title, topic
        )
        transcript_sections.append(text)
        for source_title, url in sources:
            all_sources[url] = source_title

        logger.info("Synthesizing section %d/%d", section_number, len(EPISODE_SECTIONS))
        audio_chunks.append(synthesize_section(client, text))

    episode_name = f"美股財經Podcast_{episode_date:%Y%m%d}"
    mp3_path = output_dir / f"{episode_name}.mp3"
    duration = convert_wav_chunks_to_mp3(audio_chunks, mp3_path)

    transcript_path = output_dir / f"{episode_name}.txt"
    transcript_path.write_text(
        f"美股財經 Podcast｜{episode_date.isoformat()}（台灣時間）\n\n"
        + "\n\n".join(transcript_sections)
        + "\n",
        encoding="utf-8",
    )
    sources_path = output_dir / f"{episode_name}_sources.txt"
    sources_path.write_text(
        "本集搜尋來源（Gemini grounding citations）\n"
        + "".join(f"- {title}: {url}\n" for url, title in all_sources.items()),
        encoding="utf-8",
    )
    logger.info(
        "Created %s (audio duration %.1f minutes; %d sources)",
        mp3_path,
        duration / 60,
        len(all_sources),
    )
    return mp3_path


def run_once(output_dir: Path, force: bool = False) -> None:
    today = datetime.now(TAIPEI).date()
    if not force and not is_taiwan_workday(today):
        logger.info("%s is not a Taiwan workday; skipping.", today.isoformat())
        return
    create_episode(today, output_dir)


def run_scheduler(output_dir: Path) -> None:
    logger.info("Scheduler started; daily generation time is 06:00 Asia/Taipei.")
    while True:
        next_run = next_run_at_or_after(datetime.now(TAIPEI))
        delay = max(0.0, (next_run - datetime.now(TAIPEI)).total_seconds())
        logger.info("Next run: %s", next_run.isoformat())
        time.sleep(delay)
        if is_taiwan_workday(datetime.now(TAIPEI).date()):
            try:
                run_once(output_dir)
            except (APIError, OSError, RuntimeError, ValueError):
                logger.exception("Podcast generation failed; scheduler will retry tomorrow.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Taiwan-time US-market financial podcast as an MP3."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", dest="mode", action="store_const", const="once")
    mode.add_argument("--schedule", dest="mode", action="store_const", const="schedule")
    parser.set_defaults(mode="schedule")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Generate even if today is a weekend or Taiwan public holiday (with --once).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for MP3, transcript, citations, and logs (default: {DEFAULT_OUTPUT_DIR}).",
    )
    args = parser.parse_args()
    if args.force and args.mode != "once":
        parser.error("--force can only be used with --once.")
    return args


def main() -> None:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    load_dotenv(BASE_DIR / ".env")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(args.output_dir / "podcast.log", encoding="utf-8"),
        ],
    )

    if args.mode == "once":
        run_once(args.output_dir, force=args.force)
        return
    try:
        run_scheduler(args.output_dir)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
