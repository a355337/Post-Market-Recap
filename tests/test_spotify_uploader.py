from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spotify_uploader import load_episode_metadata


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


if __name__ == "__main__":
    unittest.main()
