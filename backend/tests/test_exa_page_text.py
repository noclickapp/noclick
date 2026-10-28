"""Exa returns page text only up to a per-result bound (its ``maxCharacters``): unbounded, three searches
with page text outgrew an agent's whole context in one turn."""

import uuid
from unittest.mock import AsyncMock

import pytest

from nodes.exa_node import CONTENTS_TEXT_CHARACTERS, SEARCH_TEXT_CHARACTERS, ExaNode, ExaNodeConfig


def _node(config: dict) -> ExaNode:
    node = object.__new__(ExaNode)
    node.node_id, node.user_id, node.organization_id = "node-1", str(uuid.uuid4()), None
    node.sio = node.sid = None
    node._config = ExaNodeConfig.model_validate({"config": config, "credentials": {"api_key": "exa-key"}})
    return node


@pytest.fixture
def exa(monkeypatch):
    request = AsyncMock(return_value={"status": "success", "action": "search", "data": {"results": []}})
    monkeypatch.setattr("nodes.exa_node._exa_request", request)
    return request


@pytest.mark.parametrize("config, path, text", [
    pytest.param({"operation": "search", "query": "email APIs", "include_text": "true"}, "/search",
                 lambda body: body["contents"]["text"], id="search"),
    pytest.param({"operation": "get_contents", "urls": "https://example.org/pricing"}, "/contents",
                 lambda body: body["text"], id="get_contents"),
])
async def test_page_text_is_bounded_per_result(exa, config, path, text):
    await _node(config).execute({})
    assert exa.call_args.args[2] == path
    default = SEARCH_TEXT_CHARACTERS if config["operation"] == "search" else CONTENTS_TEXT_CHARACTERS
    assert text(exa.call_args.kwargs["json_body"]) == {"maxCharacters": default}
    # A caller (an agent reading one page in full) asks for more.
    await _node({**config, "max_characters": 60_000}).execute({})
    assert text(exa.call_args.kwargs["json_body"]) == {"maxCharacters": 60_000}


async def test_search_without_page_text_asks_for_none(exa):
    await _node({"operation": "search", "query": "email APIs"}).execute({})
    assert "contents" not in exa.call_args.kwargs["json_body"]
