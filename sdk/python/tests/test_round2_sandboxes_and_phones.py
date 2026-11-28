import asyncio

import pytest

import noclick as nc
from noclick._sync import BoundMethod
from platform_helpers import USER_ID, body, listing, user_row

SANDBOX = {"object": "sandbox", "id": "sb_1", "status": "running", "image": "python", "user_id": None,
           "expires_at": "2026-09-25T10:10:00Z", "created_at": "2026-09-25T10:00:00Z"}


def test_every_round2_method_has_sync_and_aio_forms():
    methods = {
        nc.Policy: ["get", "set"], nc.Brand: ["get", "set"],
        nc.Channel: ["create", "get"], nc.Sandbox: ["create", "get", "list"],
    }
    for cls, names in methods.items():
        for name in names:
            bound = getattr(cls, name)
            assert isinstance(bound, BoundMethod), (cls, name)
            assert asyncio.iscoroutinefunction(bound.aio), (cls, name)
    assert asyncio.iscoroutinefunction(nc.usage.aio)
    sandbox = nc.Sandbox.from_id("sb_1")
    for bound in (sandbox.exec, sandbox.terminate, sandbox.files.read, sandbox.files.write,
                  nc.User.from_id("t").verify_phone, nc.Agent.from_id("a").spawn):
        assert isinstance(bound, BoundMethod) and asyncio.iscoroutinefunction(bound.aio)


# --- sandboxes -------------------------------------------------------------------

def test_create_exec_files_terminate(api, client):
    create = api.post("/v1/sandboxes").respond(json=SANDBOX)
    run = api.post("/v1/sandboxes/sb_1/exec").respond(json={"stdout": "2\n", "stderr": "", "exit_code": 0})
    put = api.put("/v1/sandboxes/sb_1/files").respond(json={"path": "/tmp/a.txt", "size": 5})
    get = api.get("/v1/sandboxes/sb_1/files").respond(content=b"\x00\x01binary",
                                                      headers={"content-type": "application/octet-stream"})
    delete = api.delete("/v1/sandboxes/sb_1").respond(204)

    sb = nc.Sandbox.create(image="python", timeout_s=600, memory_mb=1024, network=True)
    assert body(create.calls.last.request) == {"image": "python", "timeout_s": 600, "memory_mb": 1024, "network": True}
    assert sb.id == "sb_1" and sb.expires_at.minute == 10

    result = sb.exec("python -c 'print(1 + 1)'", timeout_s=30)
    assert (result.stdout, result.exit_code, result.ok, str(result)) == ("2\n", 0, True, "2\n")
    assert body(run.calls.last.request) == {"command": "python -c 'print(1 + 1)'", "timeout_s": 30}
    sb.exec(["echo", "it's here"])
    assert body(run.calls.last.request) == {"command": "echo 'it'\"'\"'s here'"}

    sb.files.write("/tmp/a.txt", "héllo")
    request = put.calls.last.request
    assert request.url.params["path"] == "/tmp/a.txt" and request.content == "héllo".encode()
    assert request.headers["Content-Type"] == "application/octet-stream"
    assert "Idempotency-Key" in request.headers
    assert sb.files.read("/tmp/a.txt") == b"\x00\x01binary"
    assert get.calls.last.request.url.params["path"] == "/tmp/a.txt"

    sb.terminate()
    assert delete.call_count == 1 and sb.status == "terminated"


def test_a_sandboxs_shell_is_a_terminal_token_for_its_own_users_sandbox(api, client):
    opened = api.post("/v1/sandboxes/sb_1/shell").respond(json={
        "object": "sandbox_shell", "sandbox_id": "sb_1", "url": "wss://api.test/v1/terminals/attach", "token": "tok_1",
        "token_expires_at": "2026-09-25T10:02:00Z", "idle_limit_s": 900})
    shell = nc.Sandbox.from_id("sb_1", user="user_42").shell()
    assert (shell.sandbox_id, shell.url, shell.token, shell.idle_limit_s) == (
        "sb_1", "wss://api.test/v1/terminals/attach", "tok_1", 900)
    assert "tok_1" not in repr(shell)  # opens the shell: never in a log line
    assert opened.calls.last.request.headers["NoClick-User"] == "user_42"


def test_non_zero_exit_is_a_result(api, client):
    api.post("/v1/sandboxes/sb_1/exec").respond(json={"stdout": "", "stderr": "boom", "exit_code": 2})
    result = nc.Sandbox.from_id("sb_1").exec("false")
    assert not result.ok and result.stderr == "boom"


def test_context_manager_terminates_even_on_error(api, client):
    api.post("/v1/sandboxes").respond(json=SANDBOX)
    delete = api.delete("/v1/sandboxes/sb_1").respond(204)
    with pytest.raises(RuntimeError):
        with nc.Sandbox.create() as sb:
            raise RuntimeError("user code failed")
    assert delete.call_count == 1 and sb.status == "terminated"


def test_exit_tolerates_an_already_expired_sandbox(api, client):
    api.post("/v1/sandboxes").respond(json=SANDBOX)
    api.delete("/v1/sandboxes/sb_1").respond(404, json={"error": {"type": "not_found", "message": "gone"}})
    with nc.Sandbox.create():
        pass
    with pytest.raises(nc.NotFound):  # an explicit terminate still says so
        nc.Sandbox.from_id("sb_1").terminate()


async def test_sandbox_aio_and_user_scope(api, client):
    create = api.post("/v1/sandboxes").respond(json={**SANDBOX, "user_id": USER_ID})
    run = api.post("/v1/sandboxes/sb_1/exec").respond(json={"stdout": "ok", "stderr": "", "exit_code": 0})
    delete = api.delete("/v1/sandboxes/sb_1").respond(204)
    async with nc.as_user(USER_ID):
        sb = await nc.Sandbox.create.aio(image="node")
    async with sb:
        assert (await sb.exec.aio("node -v")).stdout == "ok"
    assert create.calls.last.request.headers["NoClick-User"] == USER_ID
    assert run.calls.last.request.headers["NoClick-User"] == USER_ID  # the sandbox's own user
    assert delete.call_count == 1


def test_list_and_get(api, client):
    route = api.get("/v1/sandboxes").respond(json=listing(SANDBOX))
    api.get("/v1/sandboxes/sb_1").respond(json=SANDBOX)
    with nc.as_user("user_42"):
        [sb] = nc.Sandbox.list()
    assert route.calls.last.request.headers["NoClick-User"] == "user_42"
    assert sb == nc.Sandbox.get("sb_1") and sb.image == "python"


def test_file_read_error_is_typed(api, client):
    api.get("/v1/sandboxes/sb_1/files").respond(404, json={"error": {
        "type": "not_found", "message": "No file at /nope.", "next_step": "List the directory first."}})
    with pytest.raises(nc.NotFound) as info:
        nc.Sandbox.from_id("sb_1").files.read("/nope")
    assert info.value.next_step == "List the directory first."


# --- user phones ---------------------------------------------------------------

def test_verify_then_check_phone(api, client):
    api.get(f"/v1/users/{USER_ID}").respond(json=user_row(phone="+15551234567"))
    verify = api.post(f"/v1/users/{USER_ID}/phone/verify").respond(json={
        "object": "phone_verification", "phone": "+15551234567", "status": "pending",
        "expires_at": "2026-09-25T10:10:00Z"})
    check = api.post(f"/v1/users/{USER_ID}/phone/check").respond(json=user_row(
        phone="+15551234567", phone_verified_at="2026-09-25T10:01:00Z"))
    user = nc.User.get(USER_ID)
    assert user.phone_verified_at is None
    sent = user.verify_phone()
    assert (sent.phone, sent.status) == ("+15551234567", "pending")
    assert body(verify.calls.last.request) == {}
    assert "NoClick-User" not in verify.calls.last.request.headers
    assert user.check_phone(123456) is True
    assert body(check.calls.last.request) == {"code": "123456"}
    assert user.phone_verified_at.minute == 1


def test_verify_a_new_number_and_wrong_code(api, client):
    api.get(f"/v1/users/{USER_ID}").respond(json=user_row())
    verify = api.post(f"/v1/users/{USER_ID}/phone/verify").respond(json=user_row(phone="+447700900000"))
    api.post(f"/v1/users/{USER_ID}/phone/check").respond(json={"verified": False})
    user = nc.User.from_id(USER_ID)
    sent = user.verify_phone(phone="+447700900000")
    assert body(verify.calls.last.request) == {"phone": "+447700900000"}
    assert sent.phone == "+447700900000" and user.phone == "+447700900000"
    assert user.check_phone("000000") is False
