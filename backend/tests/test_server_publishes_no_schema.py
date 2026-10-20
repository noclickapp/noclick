"""The backend's apps publish no OpenAPI schema or docs pages: their routes are the engine's own clients', and a
public /openapi.json listed every one of them. The schema is still built in-process for the code that reads it."""

import pytest

import server
from utils.route_inventory import route_paths

SCHEMA_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


@pytest.mark.parametrize("app", [server.fastapi_app, server.webhook_fastapi_app], ids=["api", "worker"])
def test_no_schema_or_docs_route_is_served(app):
    assert not SCHEMA_PATHS & set(route_paths(app))
    assert app.openapi()["paths"]
