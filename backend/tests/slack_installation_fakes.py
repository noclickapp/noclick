"""In-memory fakes for slack_installations tests (shared by tests/ and nodes/tests/).

Mimics the SQL shapes utils/slack_installations.py issues, including the
token_version bump trigger from migration 20260610120000.
"""

import json


class _FakeEncryption:
    def encrypt_credential(self, data):
        return json.dumps(data)

    def decrypt_credential(self, blob):
        return json.loads(blob)


class _FakeConn:
    """In-memory slack_installations + credentials sibling rows, mimicking the
    SQL shapes the module issues (including the token_version bump trigger)."""

    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def fetch(self, sql, *args):
        if "FROM slack_installations" in sql:
            return [dict(r) for r in self.db["installations"]]
        if "FROM credentials" in sql:
            return [{"credential": r} for r in self.db["sibling_blobs"]]
        raise AssertionError(f"unexpected fetch: {sql}")

    async def fetchrow(self, sql, *args):
        if "FROM slack_installations" in sql and "WHERE id" in sql:
            for r in self.db["installations"]:
                if r["id"] == args[0]:
                    return dict(r)
            return None
        raise AssertionError(f"unexpected fetchrow: {sql}")

    async def execute(self, sql, *args):
        if sql.strip().startswith("INSERT INTO slack_installations"):
            team_id, app_id, client_id, blob = args
            for r in self.db["installations"]:
                if (r["team_id"], r["app_id"], r["client_id"]) == (team_id, app_id, client_id):
                    return "INSERT 0 0"  # ON CONFLICT DO NOTHING
            self.db["installations"].append({
                "id": f"inst-{len(self.db['installations']) + 1}",
                "team_id": team_id, "app_id": app_id, "client_id": client_id,
                "installation": blob, "revoked_at": None, "revoked_reason": None,
                "token_version": 1,
            })
            return "INSERT 0 1"
        if sql.strip().startswith("UPDATE slack_installations"):
            blob = args[0]
            target_id = args[1]
            expected_version = args[2] if len(args) > 2 else None
            for r in self.db["installations"]:
                if r["id"] == target_id:
                    if expected_version is not None and r["token_version"] != expected_version:
                        return "UPDATE 0"
                    if r["installation"] != blob:
                        r["token_version"] += 1  # the DB trigger
                    r["installation"] = blob
                    r["revoked_at"] = None
                    return "UPDATE 1"
            return "UPDATE 0"
        raise AssertionError(f"unexpected execute: {sql}")


class _FakePool:
    def __init__(self, db):
        self.db = db

    def acquire(self):
        return _FakeConn(self.db)


def _db(installations=None, sibling_blobs=None):
    return {"installations": installations or [], "sibling_blobs": sibling_blobs or []}


def _enc(data):
    return json.dumps(data)


BOT_FIELDS = {
    "team_id": "T1", "app_id": "A1", "team_name": "Acme",
    "scope": "chat:write", "token_type": "bot", "bot_user_id": "B1",
}
