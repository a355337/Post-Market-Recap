from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
SAMPLE_PATH = BASE_DIR / "output" / "finance_voice_sample.wav"
VOICE_ENV_NAME = "GEMINI_TTS_HOST_A_VOICE"


def create_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing.")
    return genai.Client(
        api_key=api_key,
        http_options={"api_version": "v1beta"},
    )


def update_env_voice_id(voice_id: str) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    updated = False
    next_lines: list[str] = []

    for line in lines:
        if line.startswith(f"{VOICE_ENV_NAME}="):
            next_lines.append(f"{VOICE_ENV_NAME}={voice_id}")
            updated = True
        else:
            next_lines.append(line)

    if not updated:
        if next_lines and next_lines[-1].strip():
            next_lines.append("")
        next_lines.append(f"{VOICE_ENV_NAME}={voice_id}")

    ENV_PATH.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")


def list_voices(client: genai.Client) -> None:
    response = client.voices.list(type_=["prompted"], timeout=60)
    voices = response.voices or []
    if not voices:
        print("No stored prompted voices found.")
        return
    for voice in voices:
        print(f"{voice.id}\t{voice.display_name or '(no name)'}")


def create_voice(client: genai.Client) -> str:
    created = client.voices.create(
        store=True,
        timeout=60,
        voice={
            "model": "gemini-3.8-flash-tts",
            "type": "prompted",
            "display_name": "Finance Anchor TW",
            "gender": "male",
            "language_code": "zh-TW",
            "prompted": {
                "input": (
                    "沉穩、理性且專業的繁體中文美股財經主播，"
                    "中低沉音域，語速平穩，發音清晰，語氣冷靜可信。"
                )
            },
        },
    )

    voice_id = getattr(created, "id", None)
    if not isinstance(voice_id, str) or not voice_id.startswith("voice_"):
        raise RuntimeError("Voice creation did not return a voice_... ID.")

    sample = getattr(created, "sample_audio", None)
    sample_data = getattr(sample, "data", None)
    if isinstance(sample_data, str) and sample_data:
        SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        SAMPLE_PATH.write_bytes(base64.b64decode(sample_data, validate=True))
        print(f"Sample saved: {SAMPLE_PATH}")

    update_env_voice_id(voice_id)
    print(f"Voice created and saved: {voice_id}")
    print(f"Updated: {ENV_PATH}")
    return voice_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--list",
        action="store_true",
        help="List stored prompted voices.",
    )
    args = parser.parse_args()

    load_dotenv(ENV_PATH)
    client = create_client()
    if args.list:
        list_voices(client)
    else:
        create_voice(client)


if __name__ == "__main__":
    main()
