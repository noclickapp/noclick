"""Security tests for unauthenticated workflow serialization."""

import json

from fastapi import Response

import utils.public_routes as public_routes

from utils.public_routes import _sanitize_workflow_for_public


def test_public_workflow_sanitizer_removes_credentials_and_runtime_output():
    workflow = {
        "nodes": [{
            "id": "node-1",
            "data": {
                "credentialIds": {"api": "credential-1"},
                "credential_ids": ["credential-2"],
                "output": {"customer": "private"},
                "config": {"operation": "send", "message": "hello"},
            },
        }],
    }

    sanitized = _sanitize_workflow_for_public(workflow)
    data = sanitized["nodes"][0]["data"]
    assert "credentialIds" not in data
    assert "credential_ids" not in data
    assert "output" not in data
    assert data["config"] == {"operation": "send", "message": "hello"}


def test_public_workflow_sanitizer_redacts_nested_secret_containers():
    workflow = {
        "config": {
            "headers": {"X-API-Key": "secret-value"},
            "environment": {"SERVICE_PASSWORD": "secret-value"},
            "nested": {
                "api-key": "secret-value",
                "accessToken": "secret-value",
                "safe": "visible",
            },
        },
    }

    sanitized = _sanitize_workflow_for_public(workflow)
    config = sanitized["config"]
    assert config["headers"] == "[REDACTED]"
    assert config["environment"] == "[REDACTED]"
    assert config["nested"] == {
        "api-key": "[REDACTED]",
        "accessToken": "[REDACTED]",
        "safe": "visible",
    }


async def test_a_cacheable_public_response_carries_nothing_worth_caching(monkeypatch):
    """This response is served from a shared cache, so whatever it contains is
    retained by machines nobody here controls and handed to every later visitor.
    That is fine for a sanitized workflow and unacceptable for anything else, so
    the two properties are asserted together: cacheable, and stripped first."""

    class FakePool:
        """The workflow row first; every later lookup (the template it may have
        been published from) finds nothing."""

        def __init__(self):
            self.calls = 0

        async def fetchrow(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls > 1:
                return None
            return {
                "id": "workflow-1",
                "name": "Example",
                "description": "",
                "workflow": {
                    "nodes": [{
                        "id": "node-1",
                        "data": {
                            "credentialIds": {"api": "credential-1"},
                            "config": {"headers": {"X-API-Key": "secret-value"}},
                        },
                    }],
                    "edges": [],
                },
                "display_metadata": {},
                "owner_name": "Author",
            }

    monkeypatch.setattr(public_routes, "get_native_pool", lambda: FakePool())
    response = Response()

    payload = await public_routes.get_public_workflow("workflow-1", response)

    assert "public" in response.headers["Cache-Control"]
    serialized = json.dumps(payload, default=str)
    assert "secret-value" not in serialized
    assert "credential-1" not in serialized
