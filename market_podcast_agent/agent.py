from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import Agent

from podcast import (
    DEFAULT_OUTPUT_DIR,
    GEMINI_TEXT_MODEL,
    TAIPEI,
    build_adk_gemini_model,
    create_episode,
    create_subject_report as build_subject_report,
    is_taiwan_workday,
)

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def generate_daily_episode() -> dict[str, str]:
    """Generate a sourced daily market podcast and save its MP3 and transcripts."""
    episode_date = datetime.now(TAIPEI).date()
    if not is_taiwan_workday(episode_date):
        return {
            "status": "skipped",
            "message": f"{episode_date.isoformat()} is not a Taiwan workday.",
        }

    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    episode_path = create_episode(episode_date, DEFAULT_OUTPUT_DIR)
    return {"status": "created", "path": str(episode_path)}


def generate_subject_report(subject: str, target_minutes: int = 30) -> dict[str, str]:
    """Generate a sourced spoken report for a topic, between 1 and 120 minutes."""
    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = build_subject_report(
        subject,
        DEFAULT_OUTPUT_DIR,
        target_minutes=target_minutes,
    )
    return {"status": "created", "path": str(report_path)}


api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
root_agent = Agent(
    name="market_podcast_agent",
    model=build_adk_gemini_model(GEMINI_TEXT_MODEL, api_key),
    description="Generate source-cited Taiwan-focused US-market podcast episodes and reports.",
    instruction=(
        "你是台灣美股財經 Podcast 產生器。只有在使用者明確要求產生每日節目時，"
        "才呼叫 generate_daily_episode；只有在使用者明確要求主題報告時，"
        "才呼叫 generate_subject_report。主題報告未指定長度時使用預設 30 分鐘。"
        "不要把工具輸出檔案以外的內容說成已完成的生成結果。"
        "工具會呼叫資料來源與 Gemini API，並在本機建立 MP3 和逐字稿。"
    ),
    tools=[generate_daily_episode, generate_subject_report],
)
