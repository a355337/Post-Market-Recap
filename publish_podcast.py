from __future__ import annotations

import argparse
import shutil
import struct
import zlib
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree as ET

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM_NS = "http://www.w3.org/2005/Atom"
ET.register_namespace("itunes", ITUNES_NS)
ET.register_namespace("atom", ATOM_NS)


def _tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    content = kind + data
    return (
        struct.pack(">I", len(data))
        + content
        + struct.pack(">I", zlib.crc32(content) & 0xFFFFFFFF)
    )


def _create_default_cover(path: Path) -> None:
    size = 1400
    pixels = bytearray()
    for y in range(size):
        blend = y / (size - 1)
        color = (
            round(12 + 15 * blend),
            round(28 + 43 * blend),
            round(54 + 53 * blend),
        )
        row = bytearray(color * size)
        if y % 175 == 0:
            for x in range(size):
                offset = x * 3
                row[offset : offset + 3] = bytes((39, 61, 82))
        for x in range(0, size, 175):
            row[x * 3 : x * 3 + 3] = bytes((39, 61, 82))
        pixels.extend(b"\0" + row)

    points = ((110, 880), (350, 720), (570, 790), (810, 510), (1030, 580), (1260, 320))
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        steps = max(abs(x1 - x0), abs(y1 - y0))
        for step in range(steps + 1):
            x = round(x0 + (x1 - x0) * step / steps)
            y = round(y0 + (y1 - y0) * step / steps)
            for dy in range(-9, 10):
                for dx in range(-9, 10):
                    if dx * dx + dy * dy > 81:
                        continue
                    px, py = x + dx, y + dy
                    if 0 <= px < size and 0 <= py < size:
                        offset = (py * size + px) * 3
                        pixels[offset : offset + 3] = bytes((255, 190, 92))

    image = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">2I5B", size, size, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(bytes(pixels), level=9))
        + _png_chunk(b"IEND", b"")
    )
    path.write_bytes(image)


def _existing_feed_metadata(feed_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    if not feed_path.is_file():
        return {}, {}

    root = ET.parse(feed_path).getroot()
    descriptions: dict[str, str] = {}
    dates: dict[str, str] = {}
    for item in root.findall("./channel/item"):
        enclosure = item.find("enclosure")
        if enclosure is None:
            continue
        audio_name = Path(unquote(urlsplit(enclosure.get("url", "")).path)).name
        if not audio_name:
            continue
        description = item.findtext("description")
        pub_date = item.findtext("pubDate")
        if description:
            descriptions[audio_name] = description
        if pub_date:
            dates[audio_name] = pub_date
    return descriptions, dates


def _episode_description(audio_path: Path) -> str:
    sidecars = (
        audio_path.with_name(f"{audio_path.stem}_Spotify說明.txt"),
        audio_path.with_suffix(".txt"),
    )
    for sidecar in sidecars:
        if sidecar.is_file():
            description = sidecar.read_text(encoding="utf-8").strip()
            if description:
                return description[:2000]
    return f"{audio_path.stem}。"


def _write_rss(
    site_dir: Path,
    base_url: str,
    author: str,
    email: str,
    previous_descriptions: dict[str, str],
    previous_dates: dict[str, str],
) -> list[Path]:
    audio_dir = site_dir / "audio"
    audio_paths = sorted(
        audio_dir.glob("*.mp3"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    base_url = base_url.rstrip("/")
    feed_url = f"{base_url}/feed.xml"

    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "台灣上班日美股財經 Podcast"
    ET.SubElement(channel, "link").text = base_url
    ET.SubElement(channel, "description").text = (
        "每集整理美股市場、總體經濟與重要企業消息，提供繁體中文音訊節目。"
    )
    ET.SubElement(channel, "language").text = "zh-TW"
    ET.SubElement(
        channel,
        _tag(ATOM_NS, "link"),
        {"href": feed_url, "rel": "self", "type": "application/rss+xml"},
    )
    ET.SubElement(channel, _tag(ITUNES_NS, "author")).text = author
    ET.SubElement(channel, _tag(ITUNES_NS, "owner"))
    owner = channel.find(_tag(ITUNES_NS, "owner"))
    if owner is not None:
        ET.SubElement(owner, _tag(ITUNES_NS, "name")).text = author
        ET.SubElement(owner, _tag(ITUNES_NS, "email")).text = email
    ET.SubElement(channel, _tag(ITUNES_NS, "explicit")).text = "false"
    ET.SubElement(channel, _tag(ITUNES_NS, "type")).text = "episodic"
    ET.SubElement(channel, _tag(ITUNES_NS, "image"), {"href": f"{base_url}/cover.png"})
    category = ET.SubElement(channel, _tag(ITUNES_NS, "category"), {"text": "Business"})
    ET.SubElement(category, _tag(ITUNES_NS, "category"), {"text": "Investing"})

    for audio_path in audio_paths:
        relative_url = f"{base_url}/audio/{quote(audio_path.name)}"
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = audio_path.stem
        ET.SubElement(item, "link").text = relative_url
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = relative_url
        ET.SubElement(item, "description").text = (
            previous_descriptions.get(audio_path.name)
            or _episode_description(audio_path)
        )
        ET.SubElement(
            item,
            "enclosure",
            {
                "url": relative_url,
                "length": str(audio_path.stat().st_size),
                "type": "audio/mpeg",
            },
        )
        pub_date = previous_dates.get(audio_path.name)
        if pub_date is None:
            published = datetime.fromtimestamp(
                audio_path.stat().st_mtime, timezone.utc
            )
            pub_date = format_datetime(published, usegmt=True)
        ET.SubElement(item, "pubDate").text = pub_date
        ET.SubElement(item, _tag(ITUNES_NS, "author")).text = author
        ET.SubElement(item, _tag(ITUNES_NS, "explicit")).text = "false"
        ET.SubElement(item, _tag(ITUNES_NS, "episodeType")).text = "full"

    ET.indent(root, space="  ")
    ET.ElementTree(root).write(
        site_dir / "feed.xml", encoding="utf-8", xml_declaration=True
    )
    return audio_paths


def publish(
    audio_dir: Path,
    site_dir: Path,
    base_url: str,
    author: str,
    email: str,
) -> None:
    if not audio_dir.is_dir():
        raise FileNotFoundError(f"Audio directory does not exist: {audio_dir}")
    if urlsplit(base_url).scheme != "https" or not urlsplit(base_url).netloc:
        raise ValueError("The GitHub Pages base URL must be an absolute HTTPS URL.")
    if not author.strip() or not email.strip():
        raise ValueError("Podcast author and contact email must not be empty.")

    site_dir.mkdir(parents=True, exist_ok=True)
    audio_site_dir = site_dir / "audio"
    audio_site_dir.mkdir(parents=True, exist_ok=True)
    feed_path = site_dir / "feed.xml"
    previous_descriptions, previous_dates = _existing_feed_metadata(feed_path)
    generated_descriptions: dict[str, str] = {}

    for audio_path in audio_dir.glob("*.mp3"):
        shutil.copy2(audio_path, audio_site_dir / audio_path.name)
        generated_descriptions[audio_path.name] = _episode_description(audio_path)

    cover_path = site_dir / "cover.png"
    if not cover_path.is_file():
        _create_default_cover(cover_path)

    audio_paths = _write_rss(
        site_dir,
        base_url,
        author.strip(),
        email.strip(),
        {**previous_descriptions, **generated_descriptions},
        previous_dates,
    )
    episode_links = "\n".join(
        f'<li><a href="audio/{escape(quote(path.name))}">{escape(path.stem)}</a></li>'
        for path in audio_paths
    )
    (site_dir / "index.html").write_text(
        "<!doctype html>\n"
        '<html lang="zh-Hant">\n<head><meta charset="utf-8">\n'
        '<link rel="alternate" type="application/rss+xml" '
        f'title="Podcast RSS" href="{escape(feed_path.name)}">\n'
        "<title>台灣上班日美股財經 Podcast</title></head>\n"
        "<body><h1>台灣上班日美股財經 Podcast</h1>\n"
        f'<p><a href="{escape(feed_path.name)}">RSS 訂閱</a></p>\n<ul>\n'
        f"{episode_links}\n</ul></body>\n"
        "</html>\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish generated MP3 episodes and a Spotify-compatible RSS feed."
    )
    parser.add_argument("--audio-dir", type=Path, required=True)
    parser.add_argument("--site-dir", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--author", default="台灣上班日美股財經 Podcast")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    publish(args.audio_dir, args.site_dir, args.base_url, args.author, args.email)


if __name__ == "__main__":
    main()
