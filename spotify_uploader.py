from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from playwright.sync_api import (
    Browser,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_EMAIL = "a355337@gmail.com"
KEYRING_SERVICE = "spotify"
CREATORS_URL = "https://creators.spotify.com/"
LOGIN_URL = "https://creators.spotify.com/pod/login"
BrowserName = Literal["chrome", "chromium"]


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


def _fill_login_form(page: Page, email: str) -> None:
    continue_button = page.get_by_role(
        "button",
        name=re.compile(r"continue with spotify|使用 Spotify 繼續", re.IGNORECASE),
    )
    if continue_button.count():
        continue_button.first.click()

    if "accounts.spotify.com" not in page.url:
        return

    email_field = page.locator(
        'input[data-testid="login-username"], input#username'
    )
    try:
        email_field.first.wait_for(state="visible", timeout=20_000)
    except PlaywrightTimeoutError as error:
        raise RuntimeError(
            "Spotify login opened, but its email field was not found."
        ) from error
    email_field.first.fill(email)
    page.get_by_role(
        "button", name=re.compile(r"continue|繼續", re.IGNORECASE)
    ).first.click()


def _is_logged_in(page: Page) -> bool:
    return (
        page.url.startswith(CREATORS_URL)
        and page.url.split("?", 1)[0].rstrip("/") != LOGIN_URL
    )


def _wait_for_login(page: Page, password: str) -> None:
    password_submitted = False

    while not _is_logged_in(page):
        password_field = page.locator('input[type="password"]')
        if (
            not password_submitted
            and password_field.count()
            and password_field.first.is_visible()
        ):
            password_field.first.fill(password)
            password_field.first.press("Enter")
            password_submitted = True

        page.wait_for_timeout(500)


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


def _launch_browser(playwright: Playwright, browser_name: BrowserName) -> Browser:
    if browser_name == "chrome":
        return playwright.chromium.launch(channel="chrome", headless=False)
    return playwright.chromium.launch(headless=False)


def upload_episode(
    audio_path: Path,
    email: str = DEFAULT_EMAIL,
    description_path: Path | None = None,
    browser_name: BrowserName = "chrome",
) -> None:
    import keyring

    metadata = load_episode_metadata(audio_path, description_path)
    password = keyring.get_password(KEYRING_SERVICE, email)
    if password is None:
        raise RuntimeError(
            f"No Spotify password is stored in keyring for {email!r} "
            f"(service {KEYRING_SERVICE!r})."
        )

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright, browser_name)
        page = browser.new_page()
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            _fill_login_form(page, email)

            if not _is_logged_in(page):
                print(
                    "Complete any Spotify verification in the browser; the "
                    "keyring password will be entered automatically when requested. "
                    "Press Ctrl+C to cancel.",
                    flush=True,
                )
                _wait_for_login(page, password)

            print(
                "Choose the correct show and open its New episode upload form "
                "in the browser.",
                flush=True,
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
            try:
                file_input.wait_for(state="attached", timeout=180_000)
            except PlaywrightTimeoutError as error:
                raise RuntimeError(
                    "The episode upload form was not opened within three minutes."
                ) from error
            file_input.first.set_input_files(str(audio_path.resolve()))

            title_field = page.get_by_label(
                re.compile(r"title|標題", re.IGNORECASE)
            )
            try:
                title_field.wait_for(state="visible", timeout=180_000)
            except PlaywrightTimeoutError as error:
                raise RuntimeError(
                    "Spotify did not finish processing the audio upload."
                ) from error
            _fill_episode_details(page, metadata)

            print(
                f"Uploaded {audio_path.name}; review the details and close the "
                "editor with its X button to save as a draft. Do not publish.",
                flush=True,
            )
            title_field.wait_for(state="hidden", timeout=180_000)
            page.get_by_text(metadata.title, exact=True).wait_for(
                state="visible", timeout=60_000
            )
            print("Verified the episode title in Spotify for Creators.", flush=True)
        finally:
            browser.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload an MP3 to Spotify for Creators and prepare it as a draft."
    )
    parser.add_argument("audio", type=Path, help="Episode MP3 to upload.")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="Spotify login email.")
    parser.add_argument(
        "--browser",
        choices=("chrome", "chromium"),
        default="chrome",
        help="Use installed Google Chrome (default) or Playwright Chromium.",
    )
    parser.add_argument(
        "--description",
        type=Path,
        help="Description text file (defaults to the MP3's Spotify說明 sidecar).",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    args = _parse_args()
    upload_episode(args.audio, args.email, args.description, args.browser)


if __name__ == "__main__":
    main()
