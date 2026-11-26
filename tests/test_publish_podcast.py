from __future__ import annotations

import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET

from publish_podcast import ITUNES_NS, publish


class PublishPodcastTests(unittest.TestCase):
    def test_publishes_audio_and_spotify_compatible_feed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audio_dir = root / "output"
            site_dir = root / "site"
            audio_dir.mkdir()
            audio = audio_dir / "美股盤後EP2｜科技股.mp3"
            audio.write_bytes(b"mp3 bytes")
            audio.with_name(f"{audio.stem}_Spotify說明.txt").write_text(
                "本集整理科技股消息。", encoding="utf-8"
            )

            publish(
                audio_dir,
                site_dir,
                "https://example.github.io/podcast",
                "Podcast Author",
                "author@example.com",
            )

            published_audio = site_dir / "audio" / audio.name
            self.assertEqual(published_audio.read_bytes(), b"mp3 bytes")
            cover = (site_dir / "cover.png").read_bytes()
            self.assertTrue(cover.startswith(b"\x89PNG"))
            self.assertEqual(struct.unpack(">2I", cover[16:24]), (1400, 1400))
            root_element = ET.parse(site_dir / "feed.xml").getroot()
            channel = root_element.find("channel")
            self.assertIsNotNone(channel)
            assert channel is not None
            self.assertEqual(channel.findtext(f"{{{ITUNES_NS}}}author"), "Podcast Author")
            self.assertEqual(
                channel.findtext(f"{{{ITUNES_NS}}}owner/{{{ITUNES_NS}}}email"),
                "author@example.com",
            )
            item = channel.find("item")
            self.assertIsNotNone(item)
            assert item is not None
            self.assertEqual(item.findtext("description"), "本集整理科技股消息。")
            enclosure = item.find("enclosure")
            self.assertIsNotNone(enclosure)
            assert enclosure is not None
            self.assertEqual(enclosure.get("type"), "audio/mpeg")
            self.assertIn("%EF%BD%9C", enclosure.get("url", ""))
            self.assertTrue((site_dir / "index.html").is_file())

    def test_preserves_previous_feed_items_and_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audio_dir = root / "output"
            site_dir = root / "site"
            audio_dir.mkdir()
            site_dir.mkdir()
            old_audio = site_dir / "audio" / "old.mp3"
            old_audio.parent.mkdir()
            old_audio.write_bytes(b"old")
            old_url = "https://example.github.io/podcast/audio/old.mp3"
            (site_dir / "feed.xml").write_text(
                "<rss version='2.0'><channel><item>"
                "<description>Original description</description>"
                f"<enclosure url='{old_url}' length='3' type='audio/mpeg'/>"
                "<pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>"
                "</item></channel></rss>",
                encoding="utf-8",
            )
            (audio_dir / "new.mp3").write_bytes(b"new")

            publish(
                audio_dir,
                site_dir,
                "https://example.github.io/podcast",
                "Podcast Author",
                "author@example.com",
            )

            channel = ET.parse(site_dir / "feed.xml").getroot().find("channel")
            self.assertIsNotNone(channel)
            assert channel is not None
            items = channel.findall("item")
            self.assertEqual(len(items), 2)
            old_item = next(item for item in items if item.findtext("title") == "old")
            self.assertEqual(old_item.findtext("description"), "Original description")
            self.assertEqual(
                old_item.findtext("pubDate"), "Mon, 01 Jan 2024 00:00:00 GMT"
            )

    def test_rejects_non_https_pages_url(self) -> None:
        with TemporaryDirectory() as directory:
            audio_dir = Path(directory) / "output"
            audio_dir.mkdir()
            with self.assertRaisesRegex(ValueError, "absolute HTTPS URL"):
                publish(
                    audio_dir,
                    Path(directory) / "site",
                    "http://example.com",
                    "A",
                    "a@example.com",
                )


if __name__ == "__main__":
    unittest.main()
