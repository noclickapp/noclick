"""A container names itself by the task id Modal gives it now, never one cached at import.

A container restored from a memory snapshot shares the imports of the container
that built it; Modal sets the restored container's own MODAL_TASK_ID as it
restores, so an id read at import would put the snapshotting container's id on
every restored container's OAuth audit rows and spans.
"""
import os

from utils import runtime_identity


def test_container_id_is_read_from_the_environment_on_each_call(monkeypatch):
    monkeypatch.setenv("MODAL_TASK_ID", "ta-built-the-snapshot")
    assert runtime_identity.container_id() == "ta-built-the-snapshot"
    monkeypatch.setenv("MODAL_TASK_ID", "ta-restored")
    assert runtime_identity.container_id() == "ta-restored"
    monkeypatch.delenv("MODAL_TASK_ID")
    assert runtime_identity.container_id() == "local"


def test_process_pid_is_this_process():
    assert runtime_identity.process_pid() == os.getpid()
