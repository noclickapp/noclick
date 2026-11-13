"""The contract tests' seam for judging only the node types (and files) an integration's pull request changes."""
import pytest

from nodes.core.registry import NODE_REGISTRY
from tests import judged_nodes


def test_every_type_is_judged_unless_some_are_named(monkeypatch):
    monkeypatch.delenv(judged_nodes.ENV, raising=False)
    assert not judged_nodes.narrowed()
    assert judged_nodes.judged_types() == list(NODE_REGISTRY)
    assert judged_nodes.judged_types(["automation-slack", "automation-jira"]) == ["automation-slack", "automation-jira"]


def test_named_types_are_judged_alone_and_import_nothing_else(monkeypatch):
    monkeypatch.setenv(judged_nodes.ENV, "automation-slack, automation-jira")
    assert judged_nodes.narrowed()
    assert judged_nodes.judged_types() == [t for t in NODE_REGISTRY if t in {"automation-slack", "automation-jira"}]
    assert judged_nodes.judged_types(["automation-exa", "automation-jira"]) == ["automation-jira"]
    assert dict(judged_nodes.judged_classes()) == {t: NODE_REGISTRY[t] for t in ("automation-slack", "automation-jira")}


def test_a_type_the_registry_doesnt_hold_is_an_error_not_an_empty_run(monkeypatch):
    monkeypatch.setenv(judged_nodes.ENV, "automation-not-a-node")
    with pytest.raises(ValueError, match="automation-not-a-node"):
        judged_nodes.judged_types()


def test_a_scan_judges_the_changed_files_when_some_are_named(monkeypatch):
    files = [judged_nodes.ROOT / "backend/nodes/slack_node.py", judged_nodes.ROOT / "backend/nodes/jira_node.py"]
    monkeypatch.delenv(judged_nodes.FILES_ENV, raising=False)
    assert judged_nodes.judged_files(files) == files and not judged_nodes.files_narrowed()
    monkeypatch.setenv(judged_nodes.FILES_ENV, "backend/nodes/jira_node.py,frontend/public/icons/jira.svg")
    assert judged_nodes.files_narrowed()
    assert judged_nodes.judged_files(files) == files[1:]
    assert judged_nodes.judged_files([("jira", files[1])], lambda item: item[1]) == [("jira", files[1])]
