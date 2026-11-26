from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from spotify_uploader import _fill_login_form, _wait_for_login, load_episode_metadata


class _FakePasswordField:
    def __init__(self, page: "_FakeLoginPage") -> None:
        self.page = page
        self.first = self

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return self.page.state == "password"

    def fill(self, value: str) -> None:
        self.page.password = value

    def press(self, key: str) -> None:
        self.page.submitted_key = key
        self.page.state = "creators"


class _FakeLoginPage:
    def __init__(self) -> None:
        self.state = "challenge"
        self.password = ""
        self.submitted_key = ""

    @property
    def url(self) -> str:
        if self.state == "creators":
            return "https://creators.spotify.com/"
        if self.state == "password":
            return "https://accounts.spotify.com/zh-TW/password"
        return "https://challenge.spotify.com/recaptcha"

    def locator(self, selector: str) -> _FakePasswordField:
        if selector != 'input[type="password"]':
            raise AssertionError(f"Unexpected selector: {selector}")
        return _FakePasswordField(self)

    def wait_for_timeout(self, milliseconds: int) -> None:
        if milliseconds != 500:
            raise AssertionError(f"Unexpected polling interval: {milliseconds}")
        if self.state == "challenge":
            self.state = "password"


class EpisodeMetadataTests(unittest.TestCase):
    def test_loads_title_and_description_from_episode_sidecar(self) -> None:
        with TemporaryDirectory() as directory:
            audio_path = Path(directory) / "美股盤後EP2｜美股科技走勢修正.mp3"
            description_path = audio_path.with_name(
                f"{audio_path.stem}_Spotify說明.txt"
            )
            audio_path.touch()
            description_path.write_text(" 本集摘要。\n", encoding="utf-8")

            metadata = load_episode_metadata(audio_path)

        self.assertEqual(metadata.title, "美股盤後EP2｜美股科技走勢修正")
        self.assertEqual(metadata.description, "本集摘要。")

    def test_rejects_missing_description_sidecar(self) -> None:
        with TemporaryDirectory() as directory:
            audio_path = Path(directory) / "episode.mp3"
            audio_path.touch()

            with self.assertRaises(FileNotFoundError):
                load_episode_metadata(audio_path)

    def test_rejects_non_mp3_audio(self) -> None:
        with TemporaryDirectory() as directory:
            audio_path = Path(directory) / "episode.wav"
            audio_path.touch()

            with self.assertRaisesRegex(ValueError, "must be an MP3"):
                load_episode_metadata(audio_path)


class SpotifyLoginTests(unittest.TestCase):
    def test_submits_email_with_continue_button(self) -> None:
        page = Mock()
        page.url = "https://accounts.spotify.com/zh-TW/login?"
        spotify_continue = Mock()
        spotify_continue.count.return_value = 0
        email_field = Mock()
        page.locator.return_value.first = email_field
        continue_button = Mock()
        continue_button.first = Mock()
        page.get_by_role.side_effect = [spotify_continue, continue_button]

        _fill_login_form(page, "user@example.com")

        email_field.fill.assert_called_once_with("user@example.com")
        email_field.press.assert_not_called()
        continue_button.first.click.assert_called_once_with()

    def test_enters_keyring_password_after_verification_reveals_password_field(
        self,
    ) -> None:
        page = _FakeLoginPage()

        _wait_for_login(page, "secret")

        self.assertEqual(page.password, "secret")
        self.assertEqual(page.submitted_key, "Enter")


if __name__ == "__main__":
    unittest.main()
