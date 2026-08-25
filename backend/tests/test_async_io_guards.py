"""Static async-IO guards — source-inspection regression pins.

Restored subset of the deleted test_sync_on_loop_fixes.py: only the guards
whose invariants are still live in the current codebase (the DatabasePoolThread
/ proxy layer and spawn strong-reference guard are covered elsewhere or
structurally dead — see tests/test_async_helpers.py).

Invariants pinned:

- R2 hot-path helpers (upload_bytes_to_r2_async, delete_files_from_r2_async_native,
  download_bytes_from_r2_async_native) are NATIVE async: presigned URL + httpx on
  the loop, no asyncio.to_thread. Reverting reintroduces either the 2026-05-07
  sync-on-loop bug or the 2026-05-27 default-executor growth.
- The deliberately-sync boto3 batch helpers that remain ``async def``
  (upload_files_to_r2, copy_files_within_r2) wrap their boto3 work in
  asyncio.to_thread — the 2026-05-09 false-async shape (async def with naked
  sync boto3 calls pinning the loop) must not return.
- Every R2 caller routes through the shared helpers: CAS store persist,
  agent_node media uploads, CAS GC sweep, publish_handler unpublish,
  resource_handler delete.
- ServerlessFunctionNode JS execution routes QuickJS through the dedicated
  js_executor thread pool (utils.threaded_executors) via execute_js_async —
  sync execute_js on the loop pins it for up to MAX_TIMEOUT_SEC (2026-05-13).
"""

import inspect


# ============================================================================
# R2: native-async httpx helpers (upload / delete / download)
# ============================================================================

def test_upload_bytes_to_r2_async_uses_native_async_httpx():
    """Static guard: the shared R2 upload helper must use native-async httpx,
    not asyncio.to_thread + sync boto3. Reverting either way reintroduces a
    known leak (2026-05-07 sync-on-loop OR 2026-05-27 default-executor growth)."""
    from utils import r2_cloudflare

    src = inspect.getsource(r2_cloudflare.upload_bytes_to_r2_async)
    assert "asyncio.to_thread" not in src, (
        "upload_bytes_to_r2_async is back to asyncio.to_thread — that pattern "
        "reserves a default-executor worker per R2 upload and grows the unbounded "
        "asyncio thread pool under sustained load (2026-05-27 leak)."
    )
    assert "client.put(" in src and "generate_presigned_upload_url" in src, (
        "upload_bytes_to_r2_async no longer uses the httpx-presigned-URL pattern "
        "— either the 2026-05-07 sync-on-loop bug or the 2026-05-27 default-"
        "executor leak will return for every caller."
    )


def test_native_r2_delete_and_download_use_httpx_not_to_thread():
    """Static guard: the native-async DELETE batch + GET helpers in
    r2_cloudflare must use presigned URL + httpx (not asyncio.to_thread +
    boto3). They're the bottleneck for every CAS / retention caller."""
    from utils import r2_cloudflare

    delete_src = inspect.getsource(r2_cloudflare.delete_files_from_r2_async_native)
    assert "asyncio.to_thread" not in delete_src
    assert "client.delete(" in delete_src
    assert "generate_presigned_delete_url" in delete_src
    assert "asyncio.gather" in delete_src, (
        "delete_files_from_r2_async_native no longer parallelizes via "
        "asyncio.gather — sequential deletes will make per-workflow-run "
        "retention cleanup linearly slower with N."
    )

    download_src = inspect.getsource(r2_cloudflare.download_bytes_from_r2_async_native)
    assert "asyncio.to_thread" not in download_src
    assert "client.get(" in download_src
    assert "generate_presigned_download_url" in download_src


def test_r2_cloudflare_false_async_helpers_use_to_thread():
    """Static guard: upload_files_to_r2 and copy_files_within_r2 are async def
    over sync boto3 batches — they must wrap that work in asyncio.to_thread.
    If a future refactor inlines the naked sync calls again (the original
    2026-05-09 false-async bug), this fails fast."""
    from utils import r2_cloudflare

    upload_src = inspect.getsource(r2_cloudflare.upload_files_to_r2)
    assert "asyncio.to_thread" in upload_src, (
        "upload_files_to_r2 no longer wraps boto3 in asyncio.to_thread — "
        "the 2026-05-09 false-async bug has regressed (callers await it but "
        "the loop blocks on naked sync put_object)."
    )

    copy_src = inspect.getsource(r2_cloudflare.copy_files_within_r2)
    assert "asyncio.to_thread" in copy_src, (
        "copy_files_within_r2 no longer wraps boto3 in asyncio.to_thread — "
        "the 2026-05-09 false-async bug has regressed."
    )


# ============================================================================
# R2 callers: everything routes through the shared helpers
# ============================================================================

def test_cas_store_persist_uses_shared_upload_helper():
    """Static guard: the CAS store's R2 chunk upload (_put_owed) delegates to the
    shared upload helper and fans out via gather (so the no-executor guarantee
    tracked above applies to the sole node-output store)."""
    from utils.cas import store

    src = inspect.getsource(store._put_owed)
    assert "asyncio.to_thread" not in src
    assert "upload_bytes_to_r2_async" in src, (
        "CAS _put_owed no longer uses the shared upload_bytes_to_r2_async helper — "
        "direct boto3 or duplicated httpx setup will diverge from the regression "
        "guards in test_upload_bytes_to_r2_async_*."
    )
    assert "asyncio.gather" in src, (
        "CAS _put_owed no longer fans out chunk PUTs via asyncio.gather."
    )


def test_agent_node_uploads_use_shared_upload_helper():
    """Static guard: agent_node._upload_images_to_r2 and _upload_videos_to_r2
    delegate R2 uploads to a shared async helper instead of boto3+to_thread.
    Either the direct async upload (upload_bytes_to_r2_async) or the shared
    resource writer (create_resource_from_bytes, which calls that helper
    internally) satisfies the invariant."""
    from nodes import agent_node

    images_src = inspect.getsource(agent_node.AgentNode._upload_images_to_r2)
    videos_src = inspect.getsource(agent_node.AgentNode._upload_videos_to_r2)
    for name, src in [("_upload_images_to_r2", images_src), ("_upload_videos_to_r2", videos_src)]:
        assert "asyncio.to_thread" not in src, (
            f"agent_node.{name} is back to asyncio.to_thread + boto3.put_object — "
            "that's the 2026-05-27 default-executor leak shape for per-media uploads "
            "(videos can hold a worker for multiple seconds per upload)."
        )
        assert (
            "upload_bytes_to_r2_async" in src or "create_resource_from_bytes" in src
        ), (
            f"agent_node.{name} no longer uses the shared upload helper "
            "(upload_bytes_to_r2_async or create_resource_from_bytes)."
        )


def test_cas_gc_delete_uses_async_helper():
    """Static guard for the CAS store's only R2 delete path: the GC cron's
    phase_b_orphan_sweep (batch, off the request loop). It must use an async
    delete helper — never the bare sync delete_files_from_r2 (the 2026-05-09
    sync-on-loop bug)."""
    from utils.cas import gc

    src = inspect.getsource(gc.phase_b_orphan_sweep)
    assert "delete_files_from_r2_async" in src, (
        "phase_b_orphan_sweep no longer uses an async R2 delete helper — "
        "the 2026-05-09 sync-on-loop bug has regressed for CAS GC."
    )




def test_resource_handler_delete_uses_to_thread():
    """Static guard: resource_handler.delete_resource calls s3.delete_object
    directly (one-shot op, no dedicated wrapper) — it must wrap that call in
    asyncio.to_thread."""
    from wss.handlers import resource_handler

    src = inspect.getsource(resource_handler.ResourceHandler.delete_resource)
    assert "asyncio.to_thread" in src and "delete_object" in src, (
        "resource_handler.delete_resource no longer wraps s3.delete_object in "
        "asyncio.to_thread — the 2026-05-09 R2 sync-on-loop fix has regressed."
    )


# ============================================================================
# QuickJS: dedicated thread pool, never sync on the loop
# ============================================================================

def test_serverless_function_execute_js_uses_dedicated_thread_pool():
    """Static guard: ServerlessFunctionNode._execute_javascript must route
    QuickJS through the dedicated js_executor thread pool via
    execute_js_async. Direct sync execute_js calls pin the asyncio loop for
    up to MAX_TIMEOUT_SEC — regression of 2026-05-13. The dedicated pool
    (utils.threaded_executors) is also required so JS doesn't compete with
    the default asyncio thread pool for slots."""
    from nodes import serverless_function_node
    from utils import js_executor

    src = inspect.getsource(serverless_function_node.ServerlessFunctionNode._execute_javascript)
    assert "execute_js_async" in src, (
        "_execute_javascript no longer uses execute_js_async — "
        "sync QuickJS on the asyncio loop has returned (2026-05-13 fix regressed)."
    )

    # And the wrapper itself must still dispatch to the dedicated JS pool.
    wrapper_src = inspect.getsource(js_executor.execute_js_async)
    assert "run_js_threaded" in wrapper_src, (
        "execute_js_async no longer dispatches through run_js_threaded "
        "(the dedicated js_executor pool in utils.threaded_executors)."
    )
