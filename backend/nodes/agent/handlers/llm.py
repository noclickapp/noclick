"""
LLM agent handler — the in-process Agent path for standard LLM models.

Default handler for all models that aren't fast-pathed (image, video,
codex, claude-code, opencode, kling). Creates a
``coder.openai_agent.Agent``, runs it with streaming, returns the
output.
"""

import logging
import os
from typing import Any, Callable, Dict, List, Optional

from coder.openai_agent import Agent
from coder.openai_agent.config import AgentConfiguration
from nodes.agent.provider_errors import classify_and_rewrite_provider_error
from wss.sender.schema import ContentItem, ImageUrl

logger = logging.getLogger(__name__)


async def execute_llm_model(
    node,
    config,
    env_overrides: Optional[Dict[str, str]],
    user_id: Optional[str],
    user_email: Optional[str],
    *,
    custom_tools: Optional[List] = None,
    tool_configs: Optional[Dict[str, Dict]] = None,
    filesystem_configs: Optional[List[Dict[str, Any]]] = None,
    effective_conversation_id: Optional[str] = None,
    emit_callback: Optional[Callable] = None,
    final_response_ref: Optional[List[str]] = None,
    collected_images_ref: Optional[List] = None,
    final_agent_state_ref: Optional[List] = None,
) -> Dict[str, Any]:
    """
    Execute a prompt using the OpenAI Agents SDK-backed Agent.

    This handler manages the full agent lifecycle: creation, streaming,
    tool execution, and cleanup.

    Args:
        final_response_ref: Mutable list [response_str] — updated by emit_callback
        collected_images_ref: Mutable list of image URLs — updated by emit_callback
    """
    from nodes.agent_node import extract_json_from_markdown

    workspace_base = os.getenv("WORKSPACE_BASE", "/tmp/workspace")
    workspace_path = f"{workspace_base}/workflow_agents/{node.node_id}"

    # Provider-requested sandbox environment (resolved by
    # AgentNode._resolve_sandbox_mounts before dispatch) and user env vars
    # (agent_env credential). Every workflow agent gets a lazy bash sandbox
    # (Agent.create constructs the runtime; nothing boots until the first
    # execute_bash call) — these just shape its environment.
    sandbox_setups = getattr(node, "_sandbox_setups", None) or []
    user_env = getattr(node, "_user_env", None) or {}
    agent_config = AgentConfiguration.from_kwargs(
        model=config.model,
        temperature=config.temperature,
        workspace_path=workspace_path,
        env=env_overrides,
        enable_browsing=False,
        enable_mcp=False,
        enable_editor=False,
        enable_jupyter=False,
        system_prompt=config.system_prompt,
        custom_tools=custom_tools if custom_tools else None,
        filesystem_configs=filesystem_configs if filesystem_configs else None,
    )

    # Declare the agent before entering the try block so cleanup runs for every
    # successfully created runtime, including runtimes that own external resources.
    agent = None
    try:
        # Create tool executor callback
        async def tool_executor(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
            return await node._execute_tool(tool_name, arguments, tool_configs or {})

        enable_persistence = bool(config.conversation_key or node.conversation_id)
        agent = await Agent.create(
            emit_message=emit_callback,
            config=agent_config,
            conversation_id=effective_conversation_id,
            sid=node.sid,
            sio=node.sio,
            user_id=user_id,
            user_email=user_email,
            env=env_overrides,
            enable_persistence=enable_persistence,
            custom_tool_executor=tool_executor if tool_configs else None,
            organization_id=node.organization_id,
            workflow_id=node.workflow_id,
            node_id=node.node_id,
            filesystem_configs=filesystem_configs,
            conversation_key=config.conversation_key,
            sandbox_setups=sandbox_setups or None,
            user_env=user_env or None,
            execution_id=node.execution_id,
        )
        logger.info(f"[LLM] Created agent: conversation_id={effective_conversation_id}, "
                     f"persistence={enable_persistence}, conversation_key={config.conversation_key!r}")

        # Store agent reference for filesystem tool access
        node._active_agent = agent

        # Build input content
        content_items = []

        # config.message already carries the composed turn: standing
        # instructions + any trigger-event block (AgentNode.execute composes
        # it pre-dispatch so CLI harnesses get the same message).
        effective_message = config.message

        content_items.append(ContentItem(type="text", text=effective_message))

        # Auto-detect image URLs in the message and inject as multimodal content blocks.
        # Images are fetched server-side and embedded as base64 data URIs so the LLM
        # receives raw pixels regardless of whether it can make outbound network requests.
        #
        # Edge cases handled:
        #   • Size cap (10 MB raw) — streaming fetch rejects oversized files before buffering
        #   • MIME allowlist — only jpeg/png/webp/gif accepted by all providers via OpenRouter
        #   • Max 5 images — each image costs significant tokens; cap prevents context overflow
        #   • ImageUrl object — triggers FormatAwareImageContent → correct OpenRouter wire format
        #   • Per-URL try/except — one bad URL never blocks the remaining images
        from nodes.agent.handlers._media_utils import (
            extract_inline_image_urls, fetch_image_bounded, _VISION_OK_MIME,
        )
        _inline_imgs = extract_inline_image_urls(effective_message)
        if _inline_imgs:
            _to_inject = _inline_imgs[:5]
            logger.info(f"[LLM] Auto-detected {len(_inline_imgs)} inline image URL(s), injecting up to {len(_to_inject)}")
            for _img_url in _to_inject:
                try:
                    img_b64, mime_type = await fetch_image_bounded(_img_url)
                    mime_norm = mime_type.split(';')[0].strip().lower()
                    if mime_norm not in _VISION_OK_MIME:
                        logger.warning(f"[LLM] Unsupported vision MIME ({mime_norm!r}), skipping: {_img_url[:80]!r}")
                        continue
                    content_items.append(ContentItem(
                        type="image_url",
                        image_url=ImageUrl(url=f"data:{mime_norm};base64,{img_b64}", detail="auto"),
                    ))
                    logger.info(f"[LLM] Injected inline image ({mime_norm}, ~{len(img_b64) * 3 // 4 // 1024}KB): {_img_url[:80]!r}")
                except Exception as _fe:
                    logger.warning(f"[LLM] Inline image injection failed, skipping: {_img_url[:80]!r} — {_fe}")

        # Run agent. Cleanup moved to the finally block below — calling it
        # here meant exceptions during agent execution skipped cleanup
        # entirely, leaking the agent + its threads + httpx client + JSONL
        # commit loop.
        message_dict = {"content_items": content_items}
        await agent(message_dict)

        # Get final response from the mutable ref (updated by emit_callback)
        final_response = final_response_ref[0] if final_response_ref else ""
        collected_images = collected_images_ref if collected_images_ref else []

        # Upload generated images to R2
        image_urls = []
        if collected_images and node.user_id and node.workflow_id:
            image_urls = await node._upload_images_to_r2(collected_images)

        # Determine failure via two signals (either is sufficient):
        # 1. Agent state ref explicitly says 'error' (preferred — set by event converter
        #    when the agent reaches AgentState.ERROR: rate limits, auth errors, stuck loops, etc.)
        # 2. Response starts with "Error:" and no images were generated (legacy fallback
        #    for callers that don't supply final_agent_state_ref).
        final_state = final_agent_state_ref[0] if final_agent_state_ref else None
        state_failed = bool(final_state) and final_state[0] == 'error'
        response_failed = final_response.startswith("Error:") and not collected_images
        is_failed = state_failed or response_failed
        parsed_json = extract_json_from_markdown(final_response)
        output: Dict[str, Any] = {
            'type': 'agent',
            'status': 'failed' if is_failed else 'completed',
            'response': final_response,
            'model': config.model,
            'temperature': config.temperature,
        }
        if is_failed:
            output['error'] = (final_state[1] if final_state else None) or final_response
        if image_urls:
            output['images'] = image_urls
            output['image_url'] = image_urls[0]['url']
        if parsed_json is not None and not is_failed:
            if isinstance(parsed_json, dict):
                output['response'] = {'_raw': final_response, **parsed_json}
            elif isinstance(parsed_json, list):
                output['response'] = parsed_json

        return output

    except Exception as e:
        logger.error(f"[LLM] Error executing agent: {e}", exc_info=True)
        # Provider billing/auth rejections reach here as raw litellm exception
        # text ("litellm.AuthenticationError: … OpenrouterException - …"), which
        # names a library the user has never heard of and no action they can
        # take. This agent event is its own user-visible surface, so it carries
        # the rewrite.
        #
        # The exception itself is re-raised UNTOUCHED on purpose: the workflow
        # runner rewrites it at its per-node failure choke point, and rewriting
        # here too would wrap one rewrite inside another.
        await node.emit({
            'type': 'agent',
            'status': 'error',
            'error': classify_and_rewrite_provider_error(str(e)),
        })
        raise
    finally:
        # Always release resources owned by a successfully created Agent.
        if agent is not None:
            try:
                await agent.cleanup()
            except Exception as cleanup_err:
                logger.warning(
                    f"[LLM] agent.cleanup() failed (continuing): {cleanup_err}",
                    exc_info=True,
                )
