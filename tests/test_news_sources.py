from __future__ import annotations

import json
import unittest
import urllib.parse

from news_sources import SEC_8K_FEED, collect_sources, parse_feed, select_sources


class FeedParsingTests(unittest.TestCase):
    def test_parses_rss_items_and_cleans_html(self) -> None:
        payload = b"""<?xml version="1.0"?>
        <rss version="2.0"><channel><item>
          <title>Market &amp; rates</title>
          <link>https://news.example.com/market</link>
          <description><![CDATA[Stocks &amp; <b>rates</b> update]]></description>
          <pubDate>Fri, 20 Nov 2026 03:00:00 GMT</pubDate>
        </item></channel></rss>"""

        items = parse_feed(payload, "Example News", "news")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Market & rates")
        self.assertEqual(items[0].summary, "Stocks & rates update")
        self.assertEqual(items[0].url, "https://news.example.com/market")

    def test_parses_atom_links(self) -> None:
        payload = b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <title>Company filing</title>
          <link href="https://sec.example.com/filing"/>
          <summary>New filing</summary>
          <updated>2026-11-20T03:00:00Z</updated>
        </entry></feed>"""

        items = parse_feed(payload, "SEC", "sec")

        self.assertEqual(items[0].url, "https://sec.example.com/filing")
        self.assertEqual(items[0].published, "2026-11-20T03:00:00Z")

    def test_selects_section_relevant_sources_first(self) -> None:
        payload = b"""<rss><channel>
        <item><title>News item</title><link>https://example.com/news</link></item>
        </channel></rss>"""
        sources = (
            parse_feed(payload, "News", "news")
            + parse_feed(
                payload.replace(b"News item", b"Fed item")
                .replace(b"example.com/news", b"example.com/fed"),
                "Fed",
                "fed",
            )
        )
        sources = [
            source.__class__(
                source_id=f"S{index:02d}",
                category=source.category,
                source_name=source.source_name,
                title=source.title,
                url=source.url,
                published=source.published,
                summary=source.summary,
            )
            for index, source in enumerate(sources, start=1)
        ]

        selected = select_sources(3, sources)

        self.assertEqual(selected[0].category, "fed")


class SourceCollectionTests(unittest.TestCase):
    def test_collects_rss_and_labels_quotes_without_exposing_api_key(self) -> None:
        feed_payloads = {
            "https://www.cnbc.com/id/100003114/device/rss/rss.html":
                b"<rss><channel><item><title>Market</title><link>https://example.com/news</link></item></channel></rss>",
            "https://www.federalreserve.gov/feeds/press_all.xml":
                b"<rss><channel><item><title>Fed</title><link>https://example.com/fed</link></item></channel></rss>",
            "https://www.bls.gov/feed/bls_latest.rss":
                b"<rss><channel><item><title>Jobs</title><link>https://example.com/jobs</link></item></channel></rss>",
        }
        requested_urls: list[str] = []

        def requester(url: str, user_agent: str) -> bytes:
            requested_urls.append(url)
            if "api.twelvedata.com/quote" in url:
                return json.dumps(
                    {
                        "close": "100.25",
                        "change": "1.25",
                        "percent_change": "1.26",
                        "datetime": "2026-11-19",
                    }
                ).encode()
            return feed_payloads[url]

        sources, issues = collect_sources(
            sec_user_agent="TaiwanMarketPodcast/1.0 (your-real-email@example.com)",
            twelve_data_api_key="not-a-real-key",
            requester=requester,
        )

        market_sources = [source for source in sources if source.category == "market_data"]
        self.assertEqual(len(market_sources), 3)
        self.assertNotIn("not-a-real-key", "\n".join(source.url for source in sources))
        self.assertTrue(any("SEC EDGAR skipped" in issue for issue in issues))
        self.assertNotIn(SEC_8K_FEED, requested_urls)
        self.assertTrue(all(source.source_id for source in sources))

    def test_subject_search_uses_the_supplied_topic_and_assigns_unique_ids(self) -> None:
        subject = "quantum computing"
        requested_topics: list[str] = []
        feed_payload = (
            b"<rss><channel><item><title>Quantum computing update</title>"
            b"<link>https://example.com/quantum</link></item></channel></rss>"
        )

        def requester(url: str, user_agent: str) -> bytes:
            if url.startswith("https://news.google.com/rss/search?"):
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
                requested_topics.append(query["q"][0])
                return feed_payload
            if "cnbc.com" in url:
                return (
                    b"<rss><channel><item><title>Market update</title>"
                    b"<link>https://example.com/market</link></item></channel></rss>"
                )
            return b"<rss><channel></channel></rss>"

        sources, _ = collect_sources(subject=subject, requester=requester)

        topic_sources = [
            source for source in sources
            if source.source_name == "Google News topic search"
        ]
        self.assertEqual(requested_topics, [subject])
        self.assertEqual(len(topic_sources), 1)
        self.assertEqual(topic_sources[0].title, "Quantum computing update")
        self.assertEqual(len({source.source_id for source in sources}), len(sources))


if __name__ == "__main__":
    unittest.main()
