"""The agent node's video model: on the node's own Google key a Veo model runs on
Google AI Studio with it, named as AI Studio names it, and nothing is gated or
charged; on the platform key it takes the shared OpenRouter path, gated there
on its projected cost, on any plan."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from nodes.agent.config.providers import filter_provider_credential_env, get_provider_credentials
from nodes.agent.config.video import VideoConfig
from nodes.agent.handlers import video as handler

API = handler.AISTUDIO_API
SAMPLE = "https://generativelanguage.googleapis.com/v1beta/files/clip:download?alt=media"


class Node(SimpleNamespace):
    """What the handler reads off the agent node it runs for."""

    async def emit(self, output):
        self.emitted.append(output)

    async def _upload_videos_to_r2(self, videos, api_key=None):
        self.uploaded.append((videos, api_key))
        return [{"url": "https://files.example/clip.mp4", "resource_id": "r1", "mime_type": "video/mp4"}]


def node():
    return Node(user_id="u1", organization_id="org-1", workflow_id="wf-1", node_id="agent-1", emitted=[], uploaded=[])


def env_for(model, bundle):
    required, provider = get_provider_credentials(model)
    return filter_provider_credential_env(bundle, provider_name=provider, required_vars=required, cred_model=model,
                                          model_type="video")


def test_a_google_video_model_takes_the_nodes_own_google_key_and_nothing_else():
    bundle = {"GEMINI_API_KEY": "own-key", "OPENAI_API_KEY": "another"}
    assert env_for("google/veo-3.1-fast", bundle) == {"GEMINI_API_KEY": "own-key"}
    # An old id (an older client's default) is the Google model it was renamed to.
    assert env_for("veo-3", bundle) == {"GEMINI_API_KEY": "own-key"}
    # Every other video model runs on the platform's key.
    assert env_for("kwaivgi/kling-v3.0-pro", bundle) is None


@pytest.mark.parametrize("model,aistudio", [
    ("google/veo-3.1-fast", "veo-3.1-fast-generate-preview"),  # what the 20261009130000 migration renamed to
    ("google/veo-3.1", "veo-3.1-generate-preview"),
    ("google/veo-3.1-lite", "veo-3.1-lite-generate-preview"),
    # Old ids an older client still writes: renamed the migration's way first.
    ("veo-3", "veo-3.1-fast-generate-preview"),
    ("gemini/veo-3.1-generate-001", "veo-3.1-generate-preview"),
    ("vertex_ai/veo-2.0-generate-001", "veo-3.1-lite-generate-preview"),
])
async def test_a_veo_model_on_the_owners_key_runs_on_google_and_charges_nothing(monkeypatch, model, aistudio):
    start, bill = AsyncMock(), AsyncMock()
    monkeypatch.setattr(handler.media, "start_video", start)
    monkeypatch.setattr(handler.media, "bill_openrouter", bill)
    monkeypatch.setattr(handler, "AISTUDIO_POLL_S", 0)
    agent = node()
    with respx.mock(assert_all_called=True) as router:
        submit = router.post(f"{API}/models/{aistudio}:predictLongRunning").mock(
            return_value=httpx.Response(200, json={"name": "operations/op-1"}))
        router.get(f"{API}/operations/op-1").mock(side_effect=[
            httpx.Response(200, json={"done": False}),
            httpx.Response(200, json={"done": True, "response": {"generateVideoResponse": {
                "generatedSamples": [{"video": {"uri": SAMPLE, "mimeType": "video/mp4"}}]}}}),
        ])
        out = await handler.execute_video_model(
            agent, VideoConfig(model=model, system_prompt="", message="waves", veo_duration_seconds="6",
                               veo_negative_prompt="blur"),
            {"GEMINI_API_KEY": "own-key"}, "u1")

    request = submit.calls.last.request
    assert request.headers["x-goog-api-key"] == "own-key"
    assert json.loads(request.read()) == {"instances": [{"prompt": "waves"}], "parameters": {
        "aspectRatio": "16:9", "durationSeconds": 6, "resolution": "720p", "negativePrompt": "blur"}}
    # The clip is fetched with the same key and kept with the workflow.
    assert agent.uploaded == [([{"url": SAMPLE, "mime_type": "video/mp4"}], "own-key")]
    assert out["status"] == "completed" and out["video_url"] == "https://files.example/clip.mp4"
    start.assert_not_awaited()
    bill.assert_not_awaited()


async def test_google_refusing_the_owners_key_fails_the_run_with_its_words(monkeypatch):
    monkeypatch.setattr(handler.media, "start_video", AsyncMock())
    with respx.mock() as router:
        router.post(f"{API}/models/veo-3.1-fast-generate-preview:predictLongRunning").mock(
            return_value=httpx.Response(403, json={"error": {"message": "API key not valid"}}))
        with pytest.raises(RuntimeError, match="HTTP 403.*API key not valid"):
            await handler.execute_video_model(node(), VideoConfig(message="waves"), {"GOOGLE_API_KEY": "bad"}, "u1")
    handler.media.start_video.assert_not_awaited()


async def test_on_the_platform_key_any_plan_takes_the_shared_path(monkeypatch):
    """Video needs no plan: every account's job goes to the shared path, which gates it on its cost."""
    start = AsyncMock(return_value={"job_id": "job-1"})
    monkeypatch.setattr(handler.media, "start_video", start)
    monkeypatch.setattr(handler.media, "advance_video_job", AsyncMock(return_value={
        "status": "completed", "result": {"url": "https://files.example/v.mp4", "resource_id": "r2",
                                          "mime_type": "video/mp4"}}))
    monkeypatch.setattr(handler, "POLL_INTERVAL_S", 0)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: "pool")
    out = await handler.execute_video_model(node(), VideoConfig(message="waves"), None, "u1")
    assert out["video_url"] == "https://files.example/v.mp4"
    start.assert_awaited_once()
    assert start.await_args.args == ("pool",) and "check_plan" not in start.await_args.kwargs
    assert (start.await_args.kwargs["user_id"], start.await_args.kwargs["organization_id"]) == ("u1", "org-1")


@pytest.mark.parametrize("old,current", [
    ("veo-3", "google/veo-3.1-fast"),                       # an older client's default
    ("gemini/veo-3.1-fast-generate-001", "google/veo-3.1-fast"),
    ("runwayml/gen4.5", "runway/gen-4.5"),
])
async def test_an_old_video_id_runs_as_the_openrouter_model_it_was_renamed_to(monkeypatch, old, current):
    start = AsyncMock(return_value={"job_id": "job-1"})
    monkeypatch.setattr(handler.media, "start_video", start)
    monkeypatch.setattr(handler.media, "advance_video_job", AsyncMock(return_value={
        "status": "completed", "result": {"url": "https://files.example/v.mp4", "resource_id": "r2",
                                          "mime_type": "video/mp4"}}))
    monkeypatch.setattr(handler, "POLL_INTERVAL_S", 0)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: "pool")
    await handler.execute_video_model(node(), VideoConfig(model=old, message="waves", veo_duration_seconds="4"),
                                      None, "u1")
    assert start.await_args.kwargs["model"] == current
    # A Veo model takes the node's Video Settings.
    assert ("seconds" in start.await_args.kwargs) is ("veo" in current)
