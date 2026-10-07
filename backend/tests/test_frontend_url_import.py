"""URL-policy and actual credential-approval imports without MCP SDK loading."""

import ast
import importlib
import importlib.abc
from pathlib import Path
import sys
from uuid import UUID

import pytest


BACKEND = Path(__file__).resolve().parents[1]
SDK_PREFIXES = ("mcp_adapter", "fastmcp")
POLICY_CASES = (
    ({}, "https://noclick.com"),
    ({"DEV_MODE": "1"}, "http://localhost:5173"),
    ({"DEV_MODE": "0"}, "https://noclick.com"),
    ({"DEV_MODE": "true"}, "https://noclick.com"),
    ({"DEV_MODE": ""}, "https://noclick.com"),
    ({"FRONTEND_URL": "https://frontend.example.test/"}, "https://frontend.example.test/"),
    ({"VITE_PUBLIC_URL": "https://vite.example.test/"}, "https://vite.example.test/"),
    ({"FRONTEND_URL": "", "VITE_PUBLIC_URL": "https://vite.example.test/"}, "https://vite.example.test/"),
    ({"FRONTEND_URL": "https://frontend.example.test", "VITE_PUBLIC_URL": "https://vite.example.test", "DEV_MODE": "1"},
     "https://frontend.example.test"),
    ({"VITE_PUBLIC_URL": "https://vite.example.test", "DEV_MODE": "1"}, "https://vite.example.test"),
    ({"FRONTEND_URL": "", "VITE_PUBLIC_URL": "", "DEV_MODE": "1"}, "http://localhost:5173"),
    ({"FRONTEND_URL": "", "VITE_PUBLIC_URL": ""}, "https://noclick.com"),
    ({"FRONTEND_URL": " ", "VITE_PUBLIC_URL": "https://vite.example.test", "DEV_MODE": "1"}, " "),
)


def _sdk_name(name):
    return any(name == prefix or name.startswith(prefix + ".") for prefix in SDK_PREFIXES)


@pytest.fixture(scope="module", autouse=True)
def forbid_mcp_imports():
    """An import refusal detects the original defect; no module is substituted."""
    assert not any(_sdk_name(name) for name in sys.modules)
    attempts = []

    class ImportFence(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if _sdk_name(fullname):
                attempts.append(fullname)
                raise AssertionError("URL helper attempted an MCP SDK import")
            return None

    fence = ImportFence()
    sys.meta_path.insert(0, fence)
    try:
        yield attempts
    finally:
        sys.meta_path.remove(fence)
        assert attempts == []
        assert not any(_sdk_name(name) for name in sys.modules)


@pytest.fixture
def policy_environment(monkeypatch):
    for name in ("FRONTEND_URL", "VITE_PUBLIC_URL", "DEV_MODE"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def legacy_policy():
    source = BACKEND / "tests/fixtures/frontend_url/e49_policy.py"
    namespace = {}
    exec(compile(source.read_text(), str(source), "exec"), namespace)
    return namespace["get_frontend_url"]


def test_actual_approval_import_does_not_load_mcp_sdk(forbid_mcp_imports):
    assert "utils.credential_approval" not in sys.modules
    approval = importlib.import_module("utils.credential_approval")
    helper = importlib.import_module("utils.frontend_url")
    database_pool = importlib.import_module("utils.database_pool")
    assert approval.get_frontend_url is helper.get_frontend_url
    assert approval.CredentialApprovalRepo.__module__ == "repositories.credential_approvals"
    assert approval.get_native_pool is database_pool.get_native_pool
    assert forbid_mcp_imports == []


@pytest.mark.parametrize("values,expected", POLICY_CASES)
def test_policy_matches_actual_legacy_and_explicit_contract(policy_environment, legacy_policy, values, expected):
    from utils.frontend_url import get_frontend_url
    for name, value in values.items():
        policy_environment.setenv(name, value)
    assert legacy_policy() == expected
    assert get_frontend_url() == expected


def test_imported_policy_reads_later_environment_changes(policy_environment):
    from utils.frontend_url import get_frontend_url
    assert get_frontend_url() == "https://noclick.com"
    policy_environment.setenv("DEV_MODE", "1")
    assert get_frontend_url() == "http://localhost:5173"
    policy_environment.setenv("VITE_PUBLIC_URL", "https://vite.example.test")
    assert get_frontend_url() == "https://vite.example.test"
    policy_environment.setenv("FRONTEND_URL", "https://frontend.example.test")
    assert get_frontend_url() == "https://frontend.example.test"
    policy_environment.delenv("FRONTEND_URL")
    assert get_frontend_url() == "https://vite.example.test"


@pytest.mark.parametrize("status", ("pending", "rejected"))
@pytest.mark.parametrize("base", ("https://frontend.example.test", "https://frontend.example.test///"))
def test_actual_pending_result_keeps_control_envelope_and_url(policy_environment, status, base):
    from utils import credential_approval
    policy_environment.setenv("FRONTEND_URL", base)
    approval_id = UUID("00000000-0000-4000-8000-000000000123")
    result = credential_approval.pending_result({"id": approval_id, "status": status})
    assert result == {
        "status": "pending_approval" if status == "pending" else "rejected",
        "executed": False,
        "approval_id": str(approval_id),
        "approval_url": "https://frontend.example.test/credential/approval/" + str(approval_id),
        "message": "The credential owner must review this exact call. Retry the same call after approval.",
        "_halt_downstream": True,
    }


def test_existing_approval_url_monkeypatch_target_remains_local(policy_environment):
    from utils import credential_approval, frontend_url
    policy_environment.setattr(credential_approval, "get_frontend_url", lambda: "https://override.example.test/")
    result = credential_approval.pending_result({"id": "request-123", "status": "pending"})
    assert result["approval_url"] == "https://override.example.test/credential/approval/request-123"
    assert result["executed"] is False
    assert frontend_url.get_frontend_url() == "https://noclick.com"


def test_endpoint_reexport_preserves_public_function_binding(policy_environment):
    """Execute the real re-export statement only, not the SDK-dependent router."""
    from utils.frontend_url import get_frontend_url
    path = BACKEND / "mcp_adapter/auth/endpoints.py"
    module = ast.parse(path.read_text())
    exports = [node for node in module.body
               if isinstance(node, ast.ImportFrom) and node.module == "utils.frontend_url"
               and any(alias.name == "get_frontend_url" and alias.asname is None for alias in node.names)]
    assert len(exports) == 1
    assert not any(isinstance(node, ast.FunctionDef) and node.name == "get_frontend_url" for node in module.body)
    namespace = {}
    exec(compile(ast.Module(body=exports, type_ignores=[]), str(path), "exec"), namespace)
    assert namespace["get_frontend_url"] is get_frontend_url
    policy_environment.setenv("FRONTEND_URL", "https://frontend.example.test/")
    assert namespace["get_frontend_url"]() == "https://frontend.example.test/"
    policy_environment.setitem(namespace, "get_frontend_url", lambda: "https://endpoint-override.example.test")
    assert namespace["get_frontend_url"]() == "https://endpoint-override.example.test"
    assert get_frontend_url() == "https://frontend.example.test/"
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == "get_frontend_url" for node in ast.walk(module))


def test_extracted_policy_function_is_verbatim_e49():
    candidate = ast.parse((BACKEND / "utils/frontend_url.py").read_text())
    legacy = ast.parse((BACKEND / "tests/fixtures/frontend_url/e49_policy.py").read_text())
    candidate_function = next(node for node in candidate.body if isinstance(node, ast.FunctionDef))
    legacy_function = next(node for node in legacy.body if isinstance(node, ast.FunctionDef))
    assert ast.dump(candidate_function, include_attributes=False) == ast.dump(legacy_function, include_attributes=False)
