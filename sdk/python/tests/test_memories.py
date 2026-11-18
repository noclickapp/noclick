"""Memories as objects, and attaching them to agents: the routes, bodies and
parsed results the client sends and reads, against the mocked transport."""

import noclick as nc
from platform_helpers import USER_ID, agent_row, body, listing, trashed

MEM_ID = "5d1c9a3e-7b2f-4e60-8a19-3c4d6e8f0b21"
HOME_ID = "8e2f4a6c-1b3d-4f5e-9a7c-2d4f6b8e0a13"
MEMORY = {"object": "memory", "id": MEM_ID, "name": "company", "description": "What every agent should know",
          "agent_id": None, "attached_to": [{"id": "ag_1", "name": "support", "writes": False}], "entry_count": 2,
          "user_id": None, "created_at": "2026-10-19T10:00:00Z", "updated_at": "2026-10-19T10:00:00Z"}
ENTRY = {"object": "memory_entry", "name": "tone", "description": "How we write", "content": "Warm.", "version": 1,
         "updated_by": "api", "user_id": None, "conversation": None, "created_at": "2026-10-19T10:00:00Z",
         "updated_at": "2026-10-19T10:00:00Z"}


def test_memory_create_list_get_and_from_name(api, client):
    create = api.post("/v1/memories").respond(json={**MEMORY, "id": "m_2", "name": "ada-notes", "user_id": USER_ID})
    api.get("/v1/memories").respond(json=listing(MEMORY))
    api.get(f"/v1/memories/{MEM_ID}").respond(json=MEMORY)

    with nc.as_user("user_42"):
        notes = nc.Memory.create("ada-notes")
    assert body(create.calls.last.request) == {"name": "ada-notes"}
    assert create.calls.last.request.headers["NoClick-User"] == "user_42"
    assert (notes.user_id, repr(notes)) == (USER_ID, "Memory(id='m_2', name='ada-notes')")

    [company] = nc.Memory.list()
    assert (company.name, company.entry_count, company.agent_id) == ("company", 2, None)
    assert company.attached_to == [{"id": "ag_1", "name": "support", "writes": False}]
    assert nc.Memory.get(MEM_ID).description == "What every agent should know"
    assert nc.Memory.from_name("company").id == MEM_ID


def test_from_name_creates_once_and_takes_a_concurrent_create(api, client):
    api.get("/v1/memories").respond(json=listing())
    api.post("/v1/memories").respond(409, json={"error": {"type": "conflict", "message": "taken",
                                                          "existing_id": MEM_ID}})
    api.get(f"/v1/memories/{MEM_ID}").respond(json=MEMORY)
    assert nc.Memory.from_name("company", create_if_missing=True, description="d").id == MEM_ID


def test_entries_are_read_and_written_one_layer_at_a_time(api, client):
    api.get(f"/v1/memories/{MEM_ID}").respond(json=MEMORY)
    listed = api.get(f"/v1/memories/{MEM_ID}/entries").respond(json=listing({**ENTRY, "content": None}))
    read = api.get(f"/v1/memories/{MEM_ID}/entries/tone").respond(json=ENTRY)
    save = api.put(f"/v1/memories/{MEM_ID}/entries/tone").respond(json={**ENTRY, "version": 2})
    forget = api.delete(f"/v1/memories/{MEM_ID}/entries/old%20pricing").respond(204)
    company = nc.Memory.from_id(MEM_ID)

    [entry] = company.entries()
    assert (entry.name, entry.content) == ("tone", None)
    assert company.read("tone").content == "Warm."
    assert company.save("tone", "Warm, brief.", version=1).version == 2
    assert body(save.calls.last.request) == {"content": "Warm, brief.", "version": 1}
    company.search("tone", user="user_42")
    assert listed.calls.last.request.url.params["q"] == "tone"
    assert listed.calls.last.request.headers["NoClick-User"] == "user_42"   # the user's layer of the account's
    company.forget("old pricing", version=3)
    assert forget.calls.last.request.url.params["version"] == "3"
    assert read.called


def test_an_entrys_versions_read_and_restore_in_its_layer(api, client):
    api.get(f"/v1/memories/{MEM_ID}").respond(json=MEMORY)
    version = {"object": "memory_entry_version", "name": "tone", "version": 1, "current": False,
               "description": "How we write", "content": "Warm.", "user_id": None, "saved_at": "2026-10-19T10:00:00Z",
               "written_by": {"type": "api"}}
    listed = api.get(f"/v1/memories/{MEM_ID}/entries/tone/versions").respond(json=listing(
        {**version, "version": 2, "current": True, "content": None}, {**version, "content": None}))
    api.get(f"/v1/memories/{MEM_ID}/entries/tone/versions/1").respond(json=version)
    restore = api.post(f"/v1/memories/{MEM_ID}/entries/tone/versions/1/restore").respond(201, json={
        **ENTRY, "version": 3})
    company = nc.Memory.from_id(MEM_ID)

    assert [(v.version, v.current) for v in company.versions("tone", user="user_42")] == [(2, True), (1, False)]
    assert listed.calls.last.request.headers["NoClick-User"] == "user_42"
    assert company.get_version("tone", 1).content == "Warm."
    assert (company.restore("tone", 1).version, restore.call_count) == (3, 1)


def test_update_and_delete_to_the_trash(api, client):
    api.get(f"/v1/memories/{MEM_ID}").respond(json=MEMORY)
    patch = api.patch(f"/v1/memories/{MEM_ID}").respond(json={**MEMORY, "name": "handbook"})
    api.delete(f"/v1/memories/{MEM_ID}").respond(json=trashed("memory", MEM_ID, "handbook"))
    company = nc.Memory.from_id(MEM_ID)
    assert company.update(name="handbook").name == "handbook"
    assert body(patch.calls.last.request) == {"name": "handbook"}
    assert company.delete().kind == "memory"


def test_an_agent_attaches_memories_read_only_or_writable(api, client):
    api.get("/v1/memories").respond(json=listing(MEMORY))
    api.get("/v1/agents/ag_9").respond(json=agent_row(id="ag_9", name="sales", memory_id=HOME_ID, memories=[]))
    links = [{"id": MEM_ID, "writes": True}, {"id": HOME_ID, "writes": False}]
    create = api.post("/v1/agents").respond(json=agent_row(id="ag_2", memory_id="m_home", memories=links))
    sales = nc.Agent.from_id("ag_9")

    agent = nc.Agent.create("closer", instructions="hi", memories=[nc.Memory.from_name("company").writable(),
                                                                   sales.memory])
    assert body(create.calls.last.request)["memories"] == links
    assert (agent.memories, agent.memory_id) == (links, "m_home")

    # A name resolves to the memory's id, so a definition reads back the same and converges with no change.
    existing = agent_row(id="ag_1", name="support", instructions="hi", memories=[{"id": MEM_ID, "writes": False}])
    api.get("/v1/agents").respond(json=listing(existing))
    patch = api.patch("/v1/agents/ag_1").respond(json={**existing, "memories": []})
    same = nc.Agent.from_name("support", create_if_missing=True, instructions="hi", memories=["company"])
    assert same.memories == [{"id": MEM_ID, "writes": False}] and not patch.called
    api.get("/v1/agents/ag_1").respond(json=existing)
    nc.Agent.from_id("ag_1").update(memories=[])
    assert body(patch.calls.last.request) == {"memories": []}


def test_an_agents_own_memory_takes_a_memorys_names(api, client):
    api.get("/v1/agents/ag_9").respond(json=agent_row(id="ag_9", name="sales", memory_id=HOME_ID))
    api.get("/v1/agents/ag_9/memory").respond(json=listing(ENTRY))
    forget = api.delete("/v1/agents/ag_9/memory/tone").respond(204)
    own = nc.Agent.from_id("ag_9").memory
    assert [e.name for e in own.entries()] == ["tone"]
    own.forget("tone", version=1)
    assert forget.calls.last.request.url.params["version"] == "1"
