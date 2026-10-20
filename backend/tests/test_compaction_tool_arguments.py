"""A site build's commits carry whole files in their tool calls' arguments, and the compactor cut only tool results
in the model's view, never a call's arguments. So a commit of a site's pages left the turn's next call past the hard
ceiling with nothing it could cut, and a long build turn whose summaries were spent kept every file it had pushed
until its next call failed. A call's arguments are cut like its result now: they stay the call's JSON, every key and
short value as it was, each long string keeping its head and tail around a marker saying the call ran with the whole
value; the call keeps its result, and the stored history keeps everything."""

import json

import pytest

from coder.coordinator import compaction
from coder.openai_agent import output_limits
from tests.test_coordinator_compaction import (  # noqa: F401 (fixtures)
    USER, builder_request_db, check_pairs, context_db, model_data,
)

pytestmark = pytest.mark.asyncio

REPO = "6f1d2c3b-0a9e-4c8d-b7a6-5e4f3d2c1b0a"


def page(name, size):
    """``size`` characters of a page shaped like the ones a site build commits (quotes and newlines included, which
    the arguments' JSON escapes)."""
    block = (f'<section class="{name}">\n  <h2>{name.title()}</h2>\n  <p>Sourdough, pastries and "cold brew", '
             f'baked daily.</p>\n</section>\n')
    return ('<!doctype html>\n<html lang="en">\n<body>\n' + block * (size // len(block) + 1))[:size]


def commit(call_id, files):
    """A ``repos_commits_create`` call through ``api_call``, as the platform's agents make one."""
    return {"type": "function_call", "name": "api_call", "call_id": call_id, "arguments": json.dumps({
        "operation": "repos_commits_create",
        "arguments": {"repo_id": REPO, "branch": "main", "message": f"Update the bakery site ({call_id})",
                      "files": [{"path": path, "content": content} for path, content in files]}})}


def committed(call_id):
    return {"type": "function_call_output", "call_id": call_id, "output": json.dumps({
        "success": True, "response": {"object": "commit", "sha": "e56b631fdf41117506b92fb50d113bcf9f2f1674",
                                      "branch": "main", "files_changed": 4}, "next": None})}


def files_of(call):
    return json.loads(call["arguments"])["arguments"]["files"]


def assert_cut_keeps_its_shape(call, original):
    """A cut call is still its JSON: the operation, the repository and every path as they were, each file's content
    its head and tail around the marker."""
    assert call["call_id"] == original["call_id"] and call["name"] == original["name"]
    kept, whole = json.loads(call["arguments"]), json.loads(original["arguments"])
    assert kept["operation"] == whole["operation"] == "repos_commits_create"
    assert {k: v for k, v in kept["arguments"].items() if k != "files"} == \
        {k: v for k, v in whole["arguments"].items() if k != "files"}
    assert [f["path"] for f in files_of(call)] == [f["path"] for f in files_of(original)]
    for cut, file in zip(files_of(call), files_of(original)):
        if cut["content"] != file["content"]:
            assert output_limits.ARGUMENTS_HINT in cut["content"] and len(cut["content"]) < len(file["content"])
            assert cut["content"].startswith(file["content"][:20])


async def test_a_turns_commit_of_whole_pages_is_cut_in_the_models_view_and_the_turn_completes(context_db, monkeypatch):
    """Through the real streamed SDK: the model commits the site's pages in one call; its next call read the commit
    whole, past the hard ceiling, and the turn failed with "The latest messages are too large"."""
    from agents.models.interface import Model
    from openai.types.responses import (Response, ResponseCompletedEvent, ResponseFunctionToolCall,
                                        ResponseOutputMessage, ResponseOutputText)

    from coder.openai_agent import Agent
    from coder.openai_agent.config import AgentConfiguration
    from wss.sender.schema import ContentItem

    pool, _, _, _ = context_db
    await pool.execute("UPDATE conversations SET metadata='{}' WHERE conversation_id=$1", f"coordinator:{USER}")
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    budget = compaction.Budget(target=8000, hard=18000, chunk=12000, recent=2000)
    pages = [("public/index.html", page("home", 30000)), ("public/menu.html", page("menu", 30000)),
             ("public/contact.html", page("contact", 30000)), ("public/robots.txt", "User-agent: *\nAllow: /\n")]
    pushed = commit("commit-1", pages)
    seen = []

    class ModelDouble(Model):
        async def get_response(self, *args, **kwargs):
            raise AssertionError("Expected streaming")

        async def stream_response(self, system_instructions, input, *args, **kwargs):
            seen.append(input)
            check_pairs(input)
            output = ([ResponseFunctionToolCall(type="function_call", name="api_call", call_id="commit-1",
                                                arguments=pushed["arguments"])] if len(seen) == 1 else
                      [ResponseOutputMessage(id="final", type="message", role="assistant", status="completed",
                                             content=[ResponseOutputText(type="output_text", text="Committed.",
                                                                         annotations=[])])])
            response = Response.model_construct(id=f"r{len(seen)}", created_at=0, model="test", object="response",
                                                output=output, status="completed", usage=None)
            yield ResponseCompletedEvent(type="response.completed", response=response, sequence_number=0)

    async def api_call(name, arguments):
        return json.loads(committed("commit-1")["output"])

    tool = {"type": "function", "function": {"name": "api_call", "description": "Call NoClick's API", "parameters": {
        "type": "object", "properties": {"operation": {"type": "string"}, "arguments": {"type": "object"}}}}}
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    emitted = []

    async def emit(event):
        emitted.append(event)

    instance = await Agent.create(emit_message=emit, conversation_id=f"coordinator:{USER}",
                                  enable_persistence=True, user_id=USER, custom_tool_executor=api_call,
                                  config=AgentConfiguration.from_kwargs(model="gpt-4o", system_prompt="Build sites.",
                                                                        custom_tools=[tool]),
                                  call_model_input_filter=compact)
    instance._sdk_agent.model = ModelDouble()
    instance._billing_hooks = None
    try:
        await instance({"content_items": [ContentItem(type="text", text="Add a menu and a contact page.")]})
    finally:
        await instance.cleanup()

    assert not [e for e in emitted if getattr(e, "status", None) == "error"]
    assert len(seen) == 2
    [call] = [i for i in seen[1] if i.get("type") == "function_call"]
    assert_cut_keeps_its_shape(call, pushed)
    assert len(call["arguments"]) < len(pushed["arguments"]) // 10
    [result] = [i for i in seen[1] if i.get("type") == "function_call_output"]
    assert result["output"] == committed("commit-1")["output"]  # its result, under the same call id, reads whole
    assert {"role": "user", "content": "Add a menu and a contact page."} in seen[1]  # the request stays in view
    assert compaction.token_count(seen[1], "test") <= budget.hard
    # The conversation keeps the commit as the model made it.
    _, stored = await compact.repo.load()
    [kept] = [i for i in stored if i.get("type") == "function_call"]
    assert files_of(kept) == files_of(pushed)


async def test_a_long_build_turn_past_its_summaries_cuts_the_files_it_pushed_and_carries_on(context_db):
    """At the real budget, a build turn of lookups and commits the size the coordinator's own make (a page, its
    worker, robots.txt and the sitemap). Once its summaries were spent, its results were cut to stubs but every
    file it had pushed stayed whole, and its next call failed with "a safe checkpoint could not be saved"."""
    from coder.openai_agent.compaction import cut_to_floor
    from coder.openai_agent.output_limits import TOOL_OUTPUT_FLOOR, TOOL_OUTPUT_STUB

    pool, _, summary, _ = context_db
    budget = compaction.Budget()
    raw = [{"role": "user", "content": "Add a contact form, a menu page and a gallery to the bakery's site."}]
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    views, pushes = [], {}

    async def call():  # one model call, persisted first as the session does
        await pool.execute("UPDATE conversations SET metadata=jsonb_set(metadata,'{sdk_history}',$2) "
                           "WHERE conversation_id=$1", f"coordinator:{USER}", raw)
        views.append((await compact(model_data(raw))).input)

    for i in range(60):
        raw += [{"type": "function_call", "name": "api_describe", "call_id": f"d{i}",
                 "arguments": json.dumps({"operation": "repos_commits_create", "detail": "full"})},
                {"type": "function_call_output", "call_id": f"d{i}",
                 "output": f'{{"operation": "repos_commits_create", "step": {i}}} ' + "schema " * 700}]
        await call()
        pushes[f"c{i}"] = commit(f"c{i}", [("public/index.html", page(f"page-{i}", 9500)),
                                           ("worker.js", page("worker", 2300)),
                                           ("public/robots.txt", "User-agent: *\nAllow: /\n"),
                                           ("public/sitemap.xml", page("sitemap", 180))])
        raw += [pushes[f"c{i}"], committed(f"c{i}")]
        await call()

    assert summary.await_count == compaction.MAX_SUMMARIES
    overhead = compaction.token_count(["System instructions", []], "test") + 6000
    assert all(overhead + compaction.token_count(view, "test") <= budget.hard for view in views)
    view = views[-1]
    check_pairs(view)
    assert view[-2:] == raw[-2:]  # the newest commit and its result read whole
    cut = [i for i in view if i.get("type") == "function_call" and i["call_id"] in pushes and i != pushes[i["call_id"]]]
    assert cut
    for item in cut:
        assert_cut_keeps_its_shape(item, pushes[item["call_id"]])
    # A cut call reads as the same cut of it in every view, its floor's and then, once a stub, a stub from then on.
    stubbed = set()
    for each in views:
        for item in each:
            if item.get("type") == "function_call" and item["call_id"] in pushes and item != pushes[item["call_id"]]:
                original = pushes[item["call_id"]]
                floor, stub = cut_to_floor(original, TOOL_OUTPUT_FLOOR), cut_to_floor(original, TOOL_OUTPUT_STUB)
                assert item in (floor, stub) and not (item == floor and item["call_id"] in stubbed)
                if item == stub:
                    stubbed.add(item["call_id"])
    assert stubbed
    _, stored = await compact.repo.load()
    assert stored == raw


async def test_a_parallel_commit_past_the_chunk_folds_with_its_files_cut(context_db):
    """A group of parallel commits bigger than a chunk is read by the summarizer with its calls' files cut, as its
    results are; the history keeps them."""
    pool, _, summary, budget = context_db
    raw = [{"role": "user", "content": "Build the bakery's site."},
           *(commit(f"p{i}", [(f"public/page-{i}.html", page(f"page-{i}", 12000))]) for i in range(3)),
           *(committed(f"p{i}") for i in range(3)),
           {"role": "assistant", "content": "Committed the three pages."}]
    for i in range(12):
        raw += [{"role": "user", "content": f"Follow-up {i}: " + "detail " * 300},
                {"role": "assistant", "content": "Noted. " * 100}]
    raw.append({"role": "user", "content": "Is the site live?"})
    await pool.execute("UPDATE conversations SET metadata=$2 WHERE conversation_id=$1", f"coordinator:{USER}",
                       {"sdk_history": raw})
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    result = await compact(model_data(raw))
    [group] = [call.args[1] for call in summary.await_args_list
               if any(i.get("type") == "function_call" for i in call.args[1])]
    check_pairs(group)
    for item in (i for i in group if i.get("type") == "function_call"):
        assert_cut_keeps_its_shape(item, raw[1 + int(item["call_id"][1:])])
    assert any(output_limits.ARGUMENTS_HINT in i["arguments"] for i in group if i.get("type") == "function_call")
    checkpoint, stored = await compact.repo.load()
    assert checkpoint["covered"] >= 7 and stored == raw
    assert compaction.token_count(result.input, "test") <= budget.hard


async def test_arguments_cut_to_a_cap_stay_their_json_and_say_the_call_ran_whole():
    from coder.openai_agent.compaction import cut_to_floor
    from coder.openai_agent.output_limits import ARGUMENTS_HINT, TOOL_OUTPUT_FLOOR, clip_arguments

    call = commit("c", [("public/index.html", page("home", 40000)), ("public/robots.txt", "User-agent: *\n")])
    cut = clip_arguments(call["arguments"], 2000)
    assert len(cut) <= 2000 and cut == clip_arguments(call["arguments"], 2000)  # the same cut every time
    assert_cut_keeps_its_shape({**call, "arguments": cut}, call)
    assert files_of({"arguments": cut})[1]["content"] == "User-agent: *\n"  # a short value as it was
    # Even below what its keys take, the call keeps its shape; arguments that aren't JSON clip as text.
    assert_cut_keeps_its_shape({**call, "arguments": clip_arguments(call["arguments"], 50)}, call)
    assert clip_arguments("not json " * 1000, 2000).count(ARGUMENTS_HINT) == 1
    assert clip_arguments(call["arguments"], len(call["arguments"])) == call["arguments"]
    # A call is cut to the floor as a result is; what's already within it reads whole.
    assert cut_to_floor(call)["arguments"] == clip_arguments(call["arguments"], TOOL_OUTPUT_FLOOR)
    assert cut_to_floor(committed("c")) == committed("c")


async def test_a_commit_that_fits_reads_whole(context_db):
    """A commit within the ceiling is never cut: the view is the history as it was."""
    pool, _, summary, budget = context_db
    raw = [{"role": "user", "content": "Fix the typo on the menu page."},
           commit("small", [("public/menu.html", page("menu", 3000))]), committed("small")]
    await pool.execute("UPDATE conversations SET metadata=$2 WHERE conversation_id=$1", f"coordinator:{USER}",
                       {"sdk_history": raw})
    result = await compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)(model_data(raw))
    assert result.input == raw and not summary.await_count
