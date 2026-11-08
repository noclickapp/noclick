"""Offline contract checks through the actual node factory; no provider account."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import college_football_data_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-cfbd-api-key"
CASES = json.loads(
    (
        Path(__file__).parent / "fixtures/college-football-data/operations.json"
    ).read_text()
)


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="cfbd-test",
        node_type=native.CollegeFootballDataNode.integration_type,
        node_data={
            "config": config,
            "credentials": {"credential_type": native.FAMILY, "api_key": TOKEN},
        },
    )


def transport(monkeypatch, body, status=200):
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(
            status, json=body, headers={"Location": "https://example.invalid/"}
        )

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", CASES, ids=[f"college-football-data:{op}" for op in CASES]
)
async def test_college_football_data_operations_exact_routes_and_query(
    monkeypatch, operation
):
    case = CASES[operation]
    body = (
        {"patronLevel": 0, "tierName": "Free"}
        if operation == "get_account_info"
        else {"team1": "Michigan", "team2": "Ohio State"}
        if operation == "get_matchup"
        else [{"id": 1}]
    )
    requests = transport(monkeypatch, body)
    result = await node(case["config"]).run({})
    assert result == {"status": "success", "data": body, "http_status": 200}
    (request,) = requests
    assert request.method == "GET" and request.url.host == "api.collegefootballdata.com"
    assert request.url.path == case["path"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert dict(request.url.params) == {
        native.OPERATIONS[operation]["params"][k]: str(v)
        for k, v in case["config"].items()
        if k != "operation"
    }


@pytest.mark.asyncio
async def test_college_football_data_aliases_boolean_and_search_encoding(monkeypatch):
    requests = transport(monkeypatch, [])
    result = await node(
        {"operation": "list_rankings", "year": 2025, "poll": "cfp", "latest": True}
    ).run({})
    assert result["status"] == "success" and requests[-1].url.params["latest"] == "true"
    await node(
        {"operation": "search_players", "search_term": "A + B", "year": 2025}
    ).run({})
    assert requests[-1].url.params["searchTerm"] == "A + B"
    await node(
        {
            "operation": "list_player_season_stats",
            "year": 2025,
            "start_week": 1,
            "end_week": 3,
            "season_type": "regular",
        }
    ).run({})
    assert dict(requests[-1].url.params) == {
        "year": "2025",
        "startWeek": "1",
        "endWeek": "3",
        "seasonType": "regular",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [204, 301, 302, 400, 401, 403, 404, 429, 500])
async def test_college_football_data_provider_error_redacts_token_and_never_redirects(
    monkeypatch, status
):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    result = await node({"operation": "get_account_info"}).run({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,body",
    [
        ("get_account_info", None),
        ("get_account_info", {}),
        ("get_account_info", []),
        ("list_teams", {}),
        ("list_teams", [None]),
        ("get_matchup", []),
    ],
)
async def test_college_football_data_malformed_or_unauthenticated_response_fails(
    monkeypatch, operation, body
):
    transport(monkeypatch, body)
    assert (await node(CASES[operation]["config"]).run({}))["status"] == "error"


@pytest.mark.asyncio
async def test_college_football_data_empty_list_is_success_and_timeout_is_not(
    monkeypatch,
):
    transport(monkeypatch, [])
    assert (await node({"operation": "list_teams"}).run({}))["data"] == []

    def client(**kwargs):
        def fail(request):
            raise httpx.ReadTimeout(TOKEN, request=request)

        return httpx.AsyncClient(transport=httpx.MockTransport(fail), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    result = await node({"operation": "list_teams"}).run({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "list_games"},
        {"operation": "list_game_team_stats", "year": 2025},
        {"operation": "search_players"},
        {"operation": "get_matchup", "team1": "Michigan"},
        {"operation": "list_calendar", "year": -1},
        {"operation": "list_rankings", "year": 2025, "latest": True},
        {
            "operation": "list_rankings",
            "year": 2025,
            "poll": "cfp",
            "latest": True,
            "final": True,
        },
        {
            "operation": "list_player_season_stats",
            "year": 2025,
            "start_week": 4,
            "end_week": 1,
        },
        {"operation": "list_teams", "url": "https://example.invalid"},
        {"operation": "create_game"},
    ],
)
def test_college_football_data_invalid_config_rejected(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize(
    "key", ["", "Bearer abc", "https://example.com/key", "<token>", "abc\r\nX:bad"]
)
def test_college_football_data_manual_key_validation(key):
    with pytest.raises(ValidationError):
        native.CollegeFootballDataAPIKeyCredential(api_key=key)


def test_college_football_data_credential_default_and_evidence():
    credential = native.CollegeFootballDataAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == native.FAMILY and credential.api_key == TOKEN
    evidence = native.CollegeFootballDataNode.connection_evidence
    assert evidence.operation == "get_account_info" and evidence.proves == "account"
    assert len(CASES) == 22
