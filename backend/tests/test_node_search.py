"""The one ranking that finds a node type by app name or purpose (``utils/node_search.py``), over the real registry:
with some 1,265 node types, an obscure look-alike or a big API that mentions a word in passing must not come first.

Each holds by fit alone, as the open edition ranks, and with the deployment's demand (``NODE_DEMAND``) where one
registers it."""

import pytest

from utils import capabilities, node_search

pytestmark = pytest.mark.every_integration


@pytest.fixture(scope="module", params=["with demand", "fit alone"])
def demand(request):
    """One index per way of ranking, which every test in the module reads."""
    node_search._index.cache_clear()
    yield request.param
    node_search._index.cache_clear()


@pytest.fixture(autouse=True)
def ranking(demand, monkeypatch):
    # The deployment's demand is registered again before every test (tests/conftest.py).
    if demand == "fit alone":
        monkeypatch.delitem(capabilities._providers, capabilities.NODE_DEMAND, raising=False)


def first(query: str) -> str:
    return node_search.search(query, limit=1)[0].node_type


@pytest.mark.parametrize("query, node_type", [
    ("box", "automation-box"),                       # not Dropbox, Arbox or Databox
    ("zoom", "automation-zoom"),                     # not ZoomInfo or AgencyZoom
    ("x", "automation-twitter"),                     # its description: "Twitter/X"
    ("sharepoint", "automation-microsoft-sharepoint"),
    ("Google Sheets", "automation-google-sheets"),
    ("smartsheet", "automation-smartsheet"),
    ("jira", "automation-jira"),
])
def test_an_apps_own_name_finds_it_first(query, node_type):
    assert first(query) == node_type


@pytest.mark.parametrize("query", ["box", "zoom", "Google Sheets", "googlesheets", "smartsheet", "jira", "sharepoint"])
def test_a_query_that_is_an_apps_whole_name_names_it(query):
    assert node_search.is_named(query, node_search.search(query, limit=5))


@pytest.mark.parametrize("query, node_type", [
    ("upload file to sharepoint", "automation-microsoft-sharepoint"),
    ("create invoice in xero", "automation-xero"),
    ("send envelope for signature", "automation-docusign"),
])
def test_a_phrase_finds_the_app_whose_operation_does_it(query, node_type):
    assert first(query) == node_type


def test_without_demand_every_app_weighs_the_same(demand):
    if demand == "fit alone":
        assert {node_search.entry(t).demand for t in ("automation-twilio", "automation-sakari-sms")} == {None}


def test_a_word_in_passing_never_outranks_the_app_it_names():
    """Slack mentions Canva nowhere it matters; a popular app never rides its demand past the one named."""
    hits = node_search.search("canva design", limit=5)
    assert hits[0].node_type == "automation-canva"
    assert hits[0].score > 3 * hits[1].score


def test_an_app_noclick_lacks_is_not_named():
    """"close" finds iClosed and every app that closes things: none of them Close, and the search says so."""
    hits = node_search.search("close", limit=10)
    assert hits and not node_search.is_named("close", hits)
    assert node_search.search("zorblax") == []  # a word no integration has


def test_a_mistyped_type_finds_what_it_meant():
    assert "automation-microsoft-sharepoint" in node_search.nearest("automation-sharepoint")
    assert node_search.nearest("automation-googlesheets")[0] == "automation-google-sheets"


def test_every_registered_node_type_is_searchable_by_its_own_name():
    """An integration the catalog file doesn't list yet (added since it was generated) is found by its type."""
    from nodes.core.registry import NODE_REGISTRY, is_listed

    missed = [t for t in NODE_REGISTRY if not t.startswith("test-") and is_listed(t)
              and t not in {h.node_type for h in node_search.search(node_search.slug_of(t).replace("-", " "), limit=5)}]
    assert missed == []


def test_a_retired_type_is_found_only_by_a_search_scoped_to_it():
    """A retired service is in no listing (``registry.is_listed``), while a search naming its type still reads it."""
    assert "automation-humanloop" not in {h.node_type for h in node_search.search("humanloop")}
    scoped = node_search.search("humanloop", node_types=["automation-humanloop"])
    assert [h.node_type for h in scoped] == ["automation-humanloop"]


def test_stop_words_alone_find_nothing():
    assert node_search.search("the and of") == []


def test_scoring_only_the_candidates_ranks_as_scoring_every_type_does():
    """A search scores only the types the query's words, or its whole, are in (``_candidates``): every other type
    scores nothing, so the ranking is the one scoring every listed type gives."""
    from nodes.core.registry import is_listed

    for query in ("send sms", "box", "x", "googlesheets", "mail", "close", "create payment link", "sharepoint upload",
                  "zorblax", "the and of"):
        query_words, whole = list(dict.fromkeys(node_search.words(query))), node_search.compact(query)
        every = [hit for e in node_search._index()[0].values()
                 if is_listed(e.node_type) and (hit := node_search._score(e, query_words, whole)) is not None]
        every.sort(key=lambda h: (-h.score, h.entry.slug))
        assert node_search.search(query) == every, query
