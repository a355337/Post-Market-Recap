from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from typing import Callable


USER_AGENT = "TaiwanMarketPodcast/1.0"
SEC_8K_FEED = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&CIK=&type=8-K&company=&dateb=&owner=include&count=20&output=atom"
)
TWELVE_DATA_QUOTE_URL = "https://api.twelvedata.com/quote"
GOOGLE_NEWS_SEARCH_URL = "https://news.google.com/rss/search"
RSS_FEEDS = (
    (
        "CNBC US Top News",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "news",
    ),
    (
        "Federal Reserve press releases",
        "https://www.federalreserve.gov/feeds/press_all.xml",
        "fed",
    ),
    ("US Bureau of Labor Statistics", "https://www.bls.gov/feed/bls_latest.rss", "economics"),
)
MARKET_ETF_PROXIES = (
    ("SPY", "S&P 500 ETF proxy"),
    ("QQQ", "Nasdaq-100 ETF proxy"),
    ("DIA", "Dow Jones ETF proxy"),
)
SECTION_SOURCE_CATEGORIES = {
    1: ("market_data", "news"),
    2: ("economics", "fed", "news"),
    3: ("fed", "news"),
    4: ("news",),
    5: ("sec", "news"),
    6: ("market_data", "news"),
    7: ("market_data", "fed", "news"),
    8: ("news", "sec"),
    9: ("economics", "fed", "news"),
    10: ("market_data", "news", "sec", "fed", "economics"),
}
FetchBytes = Callable[[str, str], bytes]


@dataclass(frozen=True)
class SourceItem:
    source_id: str
    category: str
    source_name: str
    title: str
    url: str
    published: str
    summary: str


def fetch_bytes(url: str, user_agent: str = USER_AGENT) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read(1_000_001)
    if len(body) > 1_000_000:
        raise ValueError("Source response exceeded the 1 MB limit.")
    return body


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, names: tuple[str, ...]) -> str:
    for child in list(element):
        if _local_name(child.tag) not in names:
            continue
        text = "".join(child.itertext()).strip()
        if text:
            return text
    return ""


def _clean_summary(value: str, limit: int = 1200) -> str:
    text = re.sub(r"<[^>]*>", " ", value)
    text = html.unescape(text)
    return " ".join(text.split())[:limit]


def parse_feed(
    payload: bytes,
    source_name: str,
    category: str,
    limit: int = 8,
) -> list[SourceItem]:
    root = ET.fromstring(payload)
    entries = [
        element
        for element in root.iter()
        if _local_name(element.tag) in {"item", "entry"}
    ]
    parsed: list[SourceItem] = []
    for entry in entries:
        title = _child_text(entry, ("title",))
        url = ""
        for child in list(entry):
            if _local_name(child.tag) == "link":
                url = child.attrib.get("href", "").strip()
                if not url:
                    url = "".join(child.itertext()).strip()
                if url:
                    break
        if not title or not url or not url.startswith(("https://", "http://")):
            continue
        summary = _clean_summary(
            _child_text(entry, ("description", "summary", "encoded", "content"))
        )
        published = _child_text(entry, ("pubdate", "published", "updated", "date"))
        parsed.append(
            SourceItem(
                source_id="",
                category=category,
                source_name=source_name,
                title=_clean_summary(title, limit=300),
                url=url,
                published=published,
                summary=summary,
            )
        )
        if len(parsed) >= limit:
            break
    return parsed


def _fetch_quote(
    symbol: str,
    label: str,
    api_key: str,
    requester: FetchBytes,
) -> SourceItem:
    query = urllib.parse.urlencode({"symbol": symbol, "apikey": api_key})
    payload = json.loads(requester(f"{TWELVE_DATA_QUOTE_URL}?{query}", USER_AGENT))
    if not isinstance(payload, dict) or payload.get("status") == "error":
        message = payload.get("message", "invalid quote response") if isinstance(payload, dict) else "invalid quote response"
        raise ValueError(f"Twelve Data quote request failed for {symbol}: {message}")

    price = payload.get("close") or payload.get("price")
    if not price:
        raise ValueError(f"Twelve Data returned no closing price for {symbol}.")
    change = payload.get("change")
    percent_change = payload.get("percent_change")
    quote_parts = [f"latest close {price} USD"]
    if change not in (None, "") and percent_change not in (None, ""):
        quote_parts.append(f"change {change} USD ({percent_change}%)")
    if payload.get("datetime"):
        quote_parts.append(f"quote date {payload['datetime']}")

    return SourceItem(
        source_id="",
        category="market_data",
        source_name=f"Twelve Data {symbol} ({label})",
        title=f"{label} quote: {symbol}",
        url=f"{TWELVE_DATA_QUOTE_URL}?symbol={symbol}",
        published=str(payload.get("datetime", "")),
        summary="; ".join(quote_parts),
    )


def collect_sources(
    sec_user_agent: str = "",
    twelve_data_api_key: str = "",
    requester: FetchBytes = fetch_bytes,
    subject: str = "",
) -> tuple[list[SourceItem], list[str]]:
    collected: list[SourceItem] = []
    issues: list[str] = []

    for source_name, url, category in RSS_FEEDS:
        try:
            collected.extend(parse_feed(requester(url, USER_AGENT), source_name, category))
        except (OSError, TimeoutError, ValueError, ET.ParseError) as error:
            issues.append(f"{source_name}: {type(error).__name__}: {error}")

    if subject:
        search_query = urllib.parse.urlencode(
            {
                "q": subject,
                "hl": "zh-TW",
                "gl": "TW",
                "ceid": "TW:zh-Hant",
            }
        )
        try:
            collected.extend(
                parse_feed(
                    requester(f"{GOOGLE_NEWS_SEARCH_URL}?{search_query}", USER_AGENT),
                    "Google News topic search",
                    "news",
                )
            )
        except (OSError, TimeoutError, ValueError, ET.ParseError) as error:
            issues.append(
                f"Google News topic search: {type(error).__name__}: {error}"
            )

    sec_agent_lower = sec_user_agent.lower()
    has_real_sec_contact = (
        "@" in sec_user_agent
        and "example.com" not in sec_agent_lower
        and "your-real-email" not in sec_agent_lower
    )
    if has_real_sec_contact:
        try:
            collected.extend(
                parse_feed(
                    requester(SEC_8K_FEED, sec_user_agent),
                    "SEC EDGAR current 8-K filings",
                    "sec",
                )
            )
        except (OSError, TimeoutError, ValueError, ET.ParseError) as error:
            issues.append(f"SEC EDGAR: {type(error).__name__}: {error}")
    else:
        issues.append("SEC EDGAR skipped: configure SEC_USER_AGENT with a real contact email.")

    if twelve_data_api_key:
        for symbol, label in MARKET_ETF_PROXIES:
            try:
                collected.append(
                    _fetch_quote(symbol, label, twelve_data_api_key, requester)
                )
            except (OSError, TimeoutError) as error:
                issues.append(
                    f"Twelve Data {symbol}: network error ({type(error).__name__})."
                )
            except ValueError as error:
                issues.append(f"Twelve Data {symbol}: {type(error).__name__}: {error}")
    else:
        issues.append(
            "Market quotes skipped: configure TWELVE_DATA_API_KEY; "
            "without it, exact prices must not be stated."
        )

    unique: list[SourceItem] = []
    seen_urls: set[str] = set()
    for item in collected:
        if item.url in seen_urls:
            continue
        seen_urls.add(item.url)
        unique.append(replace(item, source_id=f"S{len(unique) + 1:02d}"))
    return unique, issues


def select_sources(
    section_number: int, sources: list[SourceItem], limit: int = 10
) -> list[SourceItem]:
    preferred_categories = SECTION_SOURCE_CATEGORIES.get(section_number, ())
    preferred = [
        item
        for category in preferred_categories
        for item in sources
        if item.category == category
    ]
    others = [item for item in sources if item.category not in preferred_categories]
    return (preferred + others)[:limit]
