from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_EMAIL = "a355337@gmail.com"
KEYRING_SERVICE = "spotify"
CREATORS_URL = "https://creators.spotify.com/"


@dataclass(frozen=True)
class EpisodeMetadata:
    title: str
    description: str


def load_episode_metadata(
    audio_path: Path, description_path: Path | None = None
) -> EpisodeMetadata:
    if not audio_path.is_file():
        raise FileNotFoundError(f"Audio file does not exist: {audio_path}")
    if audio_path.suffix.lower() != ".mp3":
        raise ValueError(f"Spotify audio file must be an MP3: {audio_path}")

    if description_path is None:
        description_path = audio_path.with_name(
            f"{audio_path.stem}_Spotify說明.txt"
        )
    if not description_path.is_file():
        raise FileNotFoundError(
            f"Spotify description file does not exist: {description_path}"
        )

    description = description_path.read_text(encoding="utf-8").strip()
    if not description:
        raise ValueError(f"Spotify description file is empty: {description_path}")
    return EpisodeMetadata(title=audio_path.stem, description=description)


def _wait_for_user(message: str) -> None:
    if not sys.stdin.isatty():
        raise RuntimeError(message)
    input(f"{message}\nPress Enter to continue...")


def _fill_login_form(page: Page, email: str, password: str) -> None:
    email_field = page.locator('input[name="username"], input[type="email"]')
    if email_field.count() and email_field.first.is_visible():
        email_field.first.fill(email)
        email_field.first.press("Enter")

    password_field = page.locator('input[type="password"]')
    try:
        password_field.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeoutError:
        return
    if password_field.is_visible():
        password_field.first.fill(password)
        password_field.first.press("Enter")


def _fill_episode_details(page: Page, metadata: EpisodeMetadata) -> None:
    title_field = page.get_by_label(re.compile(r"title|標題", re.IGNORECASE))
    description_field = page.get_by_label(
        re.compile(r"description|描述", re.IGNORECASE)
    )
    if not title_field.count() or not description_field.count():
        raise RuntimeError(
            "Could not identify the episode title and description fields. "
            "Leave the browser open and enter them manually."
        )
    title_field.first.fill(metadata.title)
    description_field.first.fill(metadata.description)


def upload_episode(
    audio_path: Path,
    email: str = DEFAULT_EMAIL,
    description_path: Path | None = None,
) -> None:
    import keyring
    from playwright.sync_api import sync_playwright

    metadata = load_episode_metadata(audio_path, description_path)
    password = keyring.get_password(KEYRING_SERVICE, email)
    if password is None:
        raise RuntimeError(
            f"No Spotify password is stored in keyring for {email!r} "
            f"(service {KEYRING_SERVICE!r})."
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=False)
        page = browser.new_page()
        try:
            page.goto(CREATORS_URL, wait_until="domcontentloaded")
            _fill_login_form(page, email, password)

            if "creators.spotify.com" not in page.url:
                _wait_for_user(
                    "Complete any Spotify verification in the opened browser."
                )
                page.wait_for_url(
                    re.compile(r"^https://creators\.spotify\.com/"),
                    timeout=180_000,
                )

            _wait_for_user(
                "In the browser, choose the correct show and open its New episode "
                "upload form."
            )
            file_input = page.locator('input[type="file"]')
            if not file_input.count():
                select_file = page.get_by_role(
                    "button",
                    name=re.compile(
                        r"select a file|choose a file|選擇檔案", re.IGNORECASE
                    ),
                )
                if select_file.count():
                    select_file.first.click()
                file_input.wait_for(state="attached", timeout=30_000)
            file_input.first.set_input_files(str(audio_path.resolve()))

            title_field = page.get_by_label(
                re.compile(r"title|標題", re.IGNORECASE)
            )
            title_field.wait_for(state="visible", timeout=180_000)
            _fill_episode_details(page, metadata)

            _wait_for_user(
                "Review the uploaded audio and episode details in the browser. "
                "Do not publish; close the editor with its X button to save as "
                "a draft, then return here."
            )
            print(
                "Episode details were filled. Confirm the draft is listed in "
                "Spotify for Creators."
            )
        finally:
            browser.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload an MP3 to Spotify for Creators and prepare it as a draft."
    )
    parser.add_argument("audio", type=Path, help="Episode MP3 to upload.")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="Spotify login email.")
    parser.add_argument(
        "--description",
        type=Path,
        help="Description text file (defaults to the MP3's Spotify說明 sidecar).",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    args = _parse_args()
    upload_episode(args.audio, args.email, args.description)


if __name__ == "__main__":
    main()
