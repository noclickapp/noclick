"""Feed parsing must not run on the event loop.

``parse_rss_feed_direct`` correctly awaits the httpx fetch, then handed the
response body straight to ``feedparser.parse`` — CPU-bound XML through expat /
xml.sax. Parsing must run off the event-loop thread so it cannot stall
unrelated handlers.
"""

import threading
from unittest.mock import AsyncMock, MagicMock, patch

import nodes.rss_node as rss_node


FEED_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Example</title><link>https://example.com</link>
  <description>d</description>
  <item><title>One</title><link>https://example.com/1</link></item>
</channel></rss>"""


def _client_returning(xml: str) -> MagicMock:
    response = MagicMock()
    response.text = xml
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


async def test_feedparser_runs_off_the_loop_thread():
    seen: list[threading.Thread] = []
    real_parse = rss_node.feedparser.parse

    def record(text):
        seen.append(threading.current_thread())
        return real_parse(text)

    with patch.object(rss_node.httpx, "AsyncClient", _client_returning(FEED_XML)), \
         patch.object(rss_node.feedparser, "parse", record):
        await rss_node.parse_rss_feed_direct("https://example.com/feed.xml")

    assert seen, "feedparser.parse never ran"
    assert seen[0] is not threading.main_thread(), \
        "feedparser.parse ran on the event loop thread"


async def test_feed_is_still_parsed_correctly():
    # Offloading must not change what the node returns.
    with patch.object(rss_node.httpx, "AsyncClient", _client_returning(FEED_XML)):
        result = await rss_node.parse_rss_feed_direct("https://example.com/feed.xml")

    assert result["feed"]["title"] == "Example"
    assert [e["title"] for e in result["entries"]] == ["One"]
