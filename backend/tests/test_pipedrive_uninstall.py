"""Verify provider-authenticated uninstall isolation and honest cleanup outcomes.

Callbacks and credentials are synthetic; SQL, row locking and rollback run on
the isolated Postgres fixture, never a provider or production database.
"""

import asyncio
import base64
import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils import pipedrive_install as install


BASIC = "Basic " + base64.b64encode(b"fixture-client:fixture-secret").decode()
PATH = "/api/credential-request/pipedrive/install/uninstall"
app = FastAPI()
app.include_router(install.router, prefix="/api/credential-request")


async def callback(body, authorization=BASIC):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://backend.example.test"
    ) as client:
        return await client.post(
            PATH, json=body, headers={"authorization": authorization}
        )


@pytest_asyncio.fixture
async def installations(real_database, monkeypatch):  # noqa: F811
    db = real_database
    monkeypatch.setenv("PIPEDRIVE_CLIENT_ID", "fixture-client")
    monkeypatch.setenv("PIPEDRIVE_CLIENT_SECRET", "fixture-secret")
    owners = [uuid.uuid4(), uuid.uuid4()]
    for owner in owners:
        await db.execute(
            "INSERT INTO auth.users(id,email) VALUES($1,$2)",
            owner,
            f"{owner}@example.test",
        )
    identity = {
        "client_id": "fixture-client",
        "company_id": str(uuid.uuid4().int % 10**15 + 1),
        "user_id": "7",
    }
    metadata = {
        "oauth_client_id": identity["client_id"],
        "pipedrive_company_id": identity["company_id"],
        "pipedrive_user_id": identity["user_id"],
    }
    variants = [
        ("target", {}, "pipedrive_oauth"),
        ("target_other_owner", {}, "pipedrive_oauth"),
        ("same_company_other_user", {"pipedrive_user_id": "8"}, "pipedrive_oauth"),
        ("same_user_other_company", {"pipedrive_company_id": "0"}, "pipedrive_oauth"),
        ("other_app", {"oauth_client_id": "another-client"}, "pipedrive_oauth"),
        ("unbound_app", {"oauth_client_id": None}, "pipedrive_oauth"),
        ("empty_app", {"oauth_client_id": ""}, "pipedrive_oauth"),
        ("other_type", {}, "other_oauth"),
    ]
    ids = {}
    for index, (name, patch, credential_type) in enumerate(variants):
        credential_id = uuid.uuid4()
        ids[name] = credential_id
        owner = owners[index % 2]
        await db.execute(
            "INSERT INTO credentials(id,owner_id,name,credential_type,credential,metadata) VALUES($1,$2,$3,$4,$5,$6)",
            credential_id,
            owner,
            name,
            credential_type,
            "opaque-fixture",
            metadata | patch,
        )
        await db.execute(
            "INSERT INTO resource_shares(resource_type,resource_id,target_type,target_user_id,shared_by) "
            "VALUES('credential',$1,'user',$2,$3)",
            credential_id,
            owners[(index + 1) % 2],
            owner,
        )
    # Sharing another resource with the same UUID must not be touched.
    await db.execute(
        "INSERT INTO resource_shares(resource_type,resource_id,target_type,target_user_id,shared_by) "
        "VALUES('workflow',$1,'user',$2,$3)",
        ids["target"],
        owners[1],
        owners[0],
    )
    yield db, identity, ids
    await db.execute(
        "DELETE FROM resource_shares WHERE resource_id = ANY($1::uuid[])",
        list(ids.values()),
    )
    await db.execute(
        "DELETE FROM credentials WHERE id = ANY($1::uuid[])", list(ids.values())
    )
    await db.execute("DELETE FROM auth.users WHERE id = ANY($1::uuid[])", owners)


async def snapshot(db, ids):
    rows = await db.fetch(
        "SELECT id FROM credentials WHERE id=ANY($1::uuid[]) ORDER BY id",
        list(ids.values()),
    )
    shares = await db.fetch(
        "SELECT resource_type,resource_id FROM resource_shares WHERE resource_id=ANY($1::uuid[]) ORDER BY resource_type,resource_id",
        list(ids.values()),
    )
    return [row["id"] for row in rows], [tuple(row) for row in shares]


async def test_uninstall_requires_app_company_and_provider_user_and_preserves_other_shares(
    installations,
):
    db, identity, ids = installations
    result = await callback(identity)
    assert result.status_code == 200
    assert result.json() == {"success": True, "removed": 2}
    remaining, shares = await snapshot(db, ids)
    preserved = set(ids.values()) - {ids["target"], ids["target_other_owner"]}
    assert set(remaining) == preserved
    assert set(shares) == {("credential", cid) for cid in preserved} | {
        ("workflow", ids["target"])
    }
    repeat = await callback(identity)
    assert repeat.json() == {"success": True, "removed": 0}
    assert await snapshot(db, ids) == (remaining, shares)


async def test_duplicate_deliveries_count_only_actual_deletes(installations):
    db, identity, ids = installations
    results = await asyncio.gather(callback(identity), callback(identity))
    assert [r.status_code for r in results] == [200, 200]
    assert sorted(r.json()["removed"] for r in results) == [0, 2]
    remaining, shares = await snapshot(db, ids)
    assert len(remaining) == 6
    assert len(shares) == 7


@pytest.mark.parametrize(
    "authorization",
    [
        "",
        "Bearer fixture",
        "Basic invalid",
        "Basic " + base64.b64encode(b"another-client:fixture-secret").decode(),
    ],
)
async def test_unauthenticated_uninstall_never_deletes(installations, authorization):
    db, identity, ids = installations
    before = await snapshot(db, ids)
    result = await callback(identity, authorization)
    assert result.status_code == 401
    assert await snapshot(db, ids) == before


@pytest.mark.parametrize(
    "patch",
    [
        {"client_id": "another-client"},
        {"client_id": None},
        {"company_id": None},
        {"user_id": None},
        {"user_id": True},
        {"user_id": 7.1},
        {"user_id": "7; DELETE FROM credentials"},
        {"company_id": "0"},
        {"company_id": "1" * 21},
    ],
)
async def test_incomplete_identity_fails_closed(installations, patch):
    db, identity, ids = installations
    before = await snapshot(db, ids)
    result = await callback(identity | patch)
    assert result.status_code == 400
    assert await snapshot(db, ids) == before


@pytest.mark.parametrize("body", [None, [], {}])
async def test_invalid_body_fails_closed(installations, body):
    db, _, ids = installations
    before = await snapshot(db, ids)
    result = await callback(body)
    assert result.status_code == 400
    assert await snapshot(db, ids) == before


@pytest.mark.parametrize("setting", ["PIPEDRIVE_CLIENT_ID", "PIPEDRIVE_CLIENT_SECRET"])
async def test_missing_backend_configuration_is_not_success(
    installations, monkeypatch, setting
):
    db, identity, ids = installations
    before = await snapshot(db, ids)
    monkeypatch.delenv(setting)
    result = await callback(identity)
    assert result.status_code == 500
    assert await snapshot(db, ids) == before


@pytest.mark.parametrize(
    "table,suppress",
    [
        ("resource_shares", False),
        ("resource_shares", True),
        ("credentials", False),
        ("credentials", True),
    ],
)
async def test_failed_or_suppressed_deletion_rolls_back_and_returns_no_success(
    installations, caplog, table, suppress
):
    db, identity, ids = installations
    before = await snapshot(db, ids)
    column = "resource_id" if table == "resource_shares" else "id"
    fault = "RETURN NULL;" if suppress else "RAISE EXCEPTION 'private-marker';"
    await db.execute(
        f"""
        CREATE FUNCTION test_pipedrive_uninstall_fault() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.{column} = '{ids['target']}'::uuid THEN {fault} END IF;
            RETURN OLD;
        END $$;
        CREATE TRIGGER test_pipedrive_uninstall_fault BEFORE DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION test_pipedrive_uninstall_fault();
    """
    )
    try:
        result = await callback(identity)
        assert result.status_code == 500
        assert result.json() == {"detail": "Pipedrive cleanup failed"}
        assert "private-marker" not in result.text + caplog.text
        assert await snapshot(db, ids) == before
    finally:
        await db.execute(
            f"DROP TRIGGER test_pipedrive_uninstall_fault ON {table}; DROP FUNCTION test_pipedrive_uninstall_fault();"
        )
