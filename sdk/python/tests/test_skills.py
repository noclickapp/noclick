"""Skills as objects, attached to agents, what a memory entry says of its writer, and what runs now: the routes,
bodies and parsed results the client sends and reads, against the mocked transport."""

import noclick as nc
from platform_helpers import agent_row, body, listing, trashed

SKILL_ID = "3a1c9a3e-7b2f-4e60-8a19-3c4d6e8f0b21"
SKILL = {"object": "skill", "id": SKILL_ID, "name": "pdf-forms", "description": "Fill PDF forms.", "always": False,
         "version": 2, "digest": "sha256:ab", "file_count": 2, "size": 120,
         "attached_to": [{"id": "ag_1", "name": "support", "pin": 1}], "user_id": None,
         "created_at": "2026-11-10T10:00:00Z", "updated_at": "2026-11-10T11:00:00Z"}
VERSION = {"object": "skill_version", "skill_id": SKILL_ID, "version": 1, "digest": "sha256:aa", "name": "pdf-forms",
           "description": "Fill PDF forms.", "always": False, "files": [{"path": "SKILL.md", "size": 60, "sha256": "s1"}],
           "size": 60, "created_by": {"type": "agent", "agent_id": "ag_1", "agent_name": "support"},
           "created_at": "2026-11-10T10:00:00Z"}


def test_a_skill_is_made_from_its_files_or_a_folder(api, client, tmp_path):
    create = api.post("/v1/skills").respond(201, json=SKILL)
    pdf = nc.Skill.create({"SKILL.md": "---\nname: pdf-forms\n---\n", "logo.png": b"\x89P"})
    assert body(create.calls.last.request) == {"files": [
        {"path": "SKILL.md", "content": "---\nname: pdf-forms\n---\n", "encoding": "utf-8"},
        {"path": "logo.png", "content": "iVA=", "encoding": "base64"}]}
    assert (pdf.name, pdf.version, pdf.file_count, pdf.always) == ("pdf-forms", 2, 2, False)
    assert pdf.attached_to == [nc.SkillAttachment("ag_1", "support", 1)]

    folder = tmp_path / "pdf-forms"
    (folder / "scripts").mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: pdf-forms\n---\n")
    (folder / "scripts" / "fill.py").write_text("print(1)\n")
    (folder / "__pycache__").mkdir()
    (folder / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    nc.Skill.from_dir(str(folder))
    assert sorted(f["path"] for f in body(create.calls.last.request)["files"]) == ["SKILL.md", "scripts/fill.py"]

    api.post("/v1/skills").respond(409, json={"error": {"type": "conflict", "message": "taken",
                                                        "existing_id": SKILL_ID}})
    api.get(f"/v1/skills/{SKILL_ID}").respond(json=SKILL)
    assert nc.Skill.create({"SKILL.md": "x"}, allow_existing=True).id == SKILL_ID


def test_versions_are_saved_read_and_restored(api, client):
    api.get(f"/v1/skills/{SKILL_ID}").respond(json=SKILL)
    save = api.post(f"/v1/skills/{SKILL_ID}/versions").respond(201, json={**SKILL, "version": 3})
    api.get(f"/v1/skills/{SKILL_ID}/versions").respond(json=listing(VERSION))
    api.get(f"/v1/skills/{SKILL_ID}/versions/1").respond(json=VERSION)
    files = api.get(f"/v1/skills/{SKILL_ID}/files").respond(json={
        "object": "skill_file", "path": "SKILL.md", "version": 1, "size": 60, "sha256": "s1", "content": "---",
        "encoding": "utf-8"})
    api.post(f"/v1/skills/{SKILL_ID}/versions/1/restore").respond(201, json={**SKILL, "version": 4})
    patch = api.patch(f"/v1/skills/{SKILL_ID}").respond(json={**SKILL, "name": "pdf-filler", "version": 5})
    pdf = nc.Skill.from_id(SKILL_ID)

    assert pdf.save_version({"run.sh": "echo hi"}, removed=["old.md"], base_version=2).version == 3
    assert body(save.calls.last.request) == {"files": [{"path": "run.sh", "content": "echo hi", "encoding": "utf-8"}],
                                             "removed": ["old.md"], "base_version": 2}
    [first] = pdf.versions()
    assert (first.version, first.created_by, first.files[0].path) == (
        1, nc.SkillAuthor("agent", "ag_1", "support"), "SKILL.md")
    assert pdf.get_version(1).digest == "sha256:aa"
    read = pdf.read("SKILL.md", version=1)
    assert (read.content, read.encoding) == ("---", "utf-8")
    assert dict(files.calls.last.request.url.params) == {"path": "SKILL.md", "version": "1"}
    assert pdf.restore(1).version == 4
    assert pdf.update(name="pdf-filler").name == "pdf-filler"
    assert body(patch.calls.last.request) == {"name": "pdf-filler"}


def test_an_agents_skills_are_listed_attached_and_deleted(api, client):
    listed = api.get("/v1/skills").respond(json=listing(SKILL))
    api.get(f"/v1/skills/{SKILL_ID}").respond(json=SKILL)
    api.get("/v1/agents/ag_1").respond(json=agent_row(skills=[{"id": SKILL_ID, "pin": 1}]))
    update = api.patch("/v1/agents/ag_1").respond(json=agent_row(skills=[{"id": SKILL_ID, "pin": 1}]))
    api.delete(f"/v1/skills/{SKILL_ID}").respond(json=trashed("skill", SKILL_ID, "pdf-forms"))

    support = nc.Agent.from_id("ag_1")
    [pdf] = nc.Skill.list(agent=support)
    assert listed.calls.last.request.url.params["agent_id"] == "ag_1"
    support.update(skills=[pdf.pinned(1), SKILL_ID])
    assert body(update.calls.last.request) == {"skills": [{"id": SKILL_ID, "pin": 1}, {"id": SKILL_ID, "pin": None}]}
    assert support.skills == [{"id": SKILL_ID, "pin": 1}]
    assert pdf.delete().kind == "skill"


def test_a_memory_entry_says_who_wrote_it_and_memories_list_by_agent(api, client):
    listed = api.get("/v1/memories").respond(json=listing())
    api.get("/v1/memories/m_1/entries/tone").respond(json={
        "object": "memory_entry", "name": "tone", "description": "How we write", "content": "Warm.", "version": 1,
        "updated_by": "agent", "written_by": {"type": "agent", "agent_id": "ag_1", "agent_name": "support",
                                              "conversation": "owner"},
        "user_id": None, "conversation": None, "created_at": None, "updated_at": None})
    nc.Memory.list(agent="ag_1")
    assert listed.calls.last.request.url.params["agent_id"] == "ag_1"
    entry = nc.Memory.from_id("m_1").read("tone")
    assert entry.written_by == nc.MemoryWriter("agent", "ag_1", "support", "owner")


def test_compute_lists_what_runs_now(api, client):
    read = api.get("/v1/compute").respond(json={"object": "list", "usd_per_hour": 0.1, "next_cursor": None, "data": [{
        "object": "compute", "kind": "machine", "id": "m_1", "name": "builder", "status": "running", "user_id": None,
        "region": "us-east", "cpu": 2, "memory_gb": 4, "started_at": "2026-11-10T10:00:00Z", "usd_per_hour": 0.1,
        "usd_per_month": 73.0, "spent_usd_today": None,
        "running": [{"agent_id": "ag_1", "agent_name": "coder", "conversation": "owner", "harness": "claude_code",
                     "state": "live"}]}]})
    [item] = nc.compute(user_filter=nc.ALL_USERS)
    assert read.calls.last.request.url.params["user_id"] == "all"
    assert (item.kind, item.usd_per_month, item.running[0]) == (
        "machine", 73.0, nc.ComputeRun("ag_1", "coder", "owner", "claude_code", "live"))
