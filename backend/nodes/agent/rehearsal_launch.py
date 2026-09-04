"""One rehearsal launcher for every surface.

The socket handler (``rehearsal:run``) and the public template page's
anonymous test runs both launch rehearsals; this module is the single
implementation so staging, the trigger-scoped dispatch, the credit gate,
and the teardown can never diverge between them. The caller owns
authentication/abuse gating and passes the USER the run executes (and
bills) as; this module owns everything after that decision.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _reply_text(out: Any) -> Optional[str]:
    """The agent's closing words as TEXT, whatever shape its output took.

    A structured agent's `response` is a parsed dict, and the done frame's
    `reply` is typed str — passing the dict through failed Pydantic validation
    inside _emit_progress's never-raise guard, so the frame silently vanished
    and the Test Run screen spun forever (2026-08-21). The dict's `_raw` holds
    the model's literal reply; anything else structured is serialized."""
    if isinstance(out, str):
        return out
    if not isinstance(out, dict):
        return None
    for key in ('output', 'response', 'text'):
        value = out.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, dict):
            raw = value.get('_raw')
            if isinstance(raw, str) and raw.strip():
                return raw
            return json.dumps(value, ensure_ascii=False, default=str)
    return None


def public_model_pin(config: Dict[str, Any]) -> Dict[str, str]:
    """Config override pinning an agent to the platform default model for
    ANONYMOUS template-page runs, empty when its configured model already runs
    credential-free.

    Templates default to CLI harnesses, which are strict-BYOK
    (validate_provider_credentials — no platform key is ever injected), and the
    template owner ships no harness credential: respecting the harness sent a
    keyless codex turn to OpenAI (401, 2026-08-12). The SDK path on an
    openrouter/* model is the one credential-free, cost-captured configuration,
    so harness agents and BYOK SDK models pin to it; media agents and
    already-openrouter agents keep their config. In-product rehearsals never
    pin — the user's real harness is part of what they're testing."""
    from nodes.agent.config.base import infer_model_type
    from nodes.agent.config.llm import DEFAULT_LLM_AGENT_MODEL
    from nodes.agent.config.providers import WRAPPER_ID_BY_MODEL_TYPE

    model_type = infer_model_type(dict(config)).get('model_type', 'llm')
    model = str(config.get('model') or '')
    if model_type in WRAPPER_ID_BY_MODEL_TYPE or (
        model_type == 'llm' and model and not model.startswith('openrouter/')
    ):
        return {"model": DEFAULT_LLM_AGENT_MODEL, "model_type": "llm"}
    return {}


async def launch_rehearsal(
    *,
    workflow_id: str,
    scenario_key: str,
    lead_patch: Optional[Dict[str, str]] = None,
    user_id: str,
    sid: Optional[str] = None,
    public: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    """Stage + start a rehearsal in the background.

    Returns ``(conversation_id, None)`` on launch, ``(None, error)`` with a
    user-facing message otherwise. ``public=True`` buffers progress frames in
    Redis for socketless watchers (the template page's polling endpoint).
    """
    from nodes.agent.rehearsal import (
        RehearsalUnavailable,
        emit_rehearsal_finished,
        end_rehearsal,
        rehearsal_conversation_id,
        resolve_trigger_node_id,
        start_rehearsal,
    )
    from nodes.agent.rehearsal_scenarios import (
        GENERIC_KEY_PREFIX,
        SCENARIOS,
        SCENARIO_TRIGGER_NODE_TYPES,
        apply_lead_patch,
        make_generic_scenario,
    )
    from utils.socket_singleton import get_sio
    from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

    if scenario_key.startswith(GENERIC_KEY_PREFIX):
        # The catch-all: any trigger type without an authored situation runs
        # against a staged sample event delivered as raw JSON.
        scenario = make_generic_scenario(scenario_key[len(GENERIC_KEY_PREFIX):])
    else:
        scenario = SCENARIOS.get(scenario_key)
    if scenario is None:
        return None, f"Unknown rehearsal scenario '{scenario_key}'"

    execution_handler = WorkflowExecutionHandler(get_sio())
    fetched = await execution_handler._fetch_workflow(workflow_id, user_id)
    if not fetched:
        return None, "Workflow not found"
    nodes, edges, _org, _vars, _settings = fetched

    trigger_type = (
        scenario_key[len(GENERIC_KEY_PREFIX):]
        if scenario_key.startswith(GENERIC_KEY_PREFIX)
        else SCENARIO_TRIGGER_NODE_TYPES.get(scenario_key)
    )
    trigger_node_id = (
        await resolve_trigger_node_id(nodes, edges, trigger_type) if trigger_type else None
    )
    if not trigger_node_id:
        # Without a stageable trigger node the fabricated event has nowhere
        # to land — either the type is absent, or its only node is wired as
        # the agent's tool provider (whose payloads the runner drops).
        return None, (
            f"This workflow has no {trigger_type} trigger wired toward an "
            f"agent for the '{scenario_key}' scenario to arrive at"
        )

    if lead_patch:
        # Edits are applied to the PAYLOAD, not just the card — an edit the
        # run ignores is a lying control.
        try:
            scenario = apply_lead_patch(trigger_type, scenario, lead_patch)
        except ValueError as e:
            return None, str(e)

    # Pre-flight credit gate on the BILLING user (organization attribution policy for org
    # workflows). The world model's fabricated answers charge as Agent
    # Testing per call, and a BYOK agent's own calls never pass through
    # BillingHooks' balance check — this gate is the only one bracketing
    # that spend. Enterprise (None) skips. For public runs `user_id` IS the
    # template owner, so this is also the hard ceiling on anonymous spend.
    from billing.usage_tracker import usage_tracker as _usage_tracker

    billing_user = await _usage_tracker.resolve_billing_user_id(
        user_id, str(_org) if _org else None
    )
    remaining = await _usage_tracker.check_credit_balance(billing_user)
    if remaining is not None and remaining <= 0:
        from billing.exceptions import insufficient_credits_message

        return None, insufficient_credits_message(remaining, 0.01)

    conversation_id = rehearsal_conversation_id(workflow_id, uuid.uuid4().hex[:8])
    try:
        await start_rehearsal(
            conversation_id, scenario, user_id=user_id, sid=sid,
            organization_id=str(_org) if _org else None, public=public,
        )
    except RehearsalUnavailable as e:
        return None, str(e)

    # Every agent in the graph gets its history keyed to THIS rehearsal.
    # Without it a staged run writes fabricated exchanges into the agent's
    # real conversation memory, which then leak into live runs — and two
    # rehearsals sharing one key interleave into the same history.
    agent_overrides = {
        node['id']: {
            "conversation_key": conversation_id,
            **(public_model_pin(node.get('config') or {}) if public else {}),
        }
        for node in nodes
        if node.get('type') == 'agent'
    }

    from wss.receiver.client_events import WorkflowExecuteRequest

    async def _run() -> None:
        finish = True
        try:
            result = await execution_handler.handle_execute(
                sid or "",
                WorkflowExecuteRequest(
                    workflow_id=workflow_id,
                    conversation_id=conversation_id,
                    trigger_source='manual',
                    # Real-delivery semantics: only the subgraph reachable
                    # from the fired trigger runs (providers backfilled).
                    start_node_id=trigger_node_id,
                    config_overrides={
                        **agent_overrides,
                        trigger_node_id: {
                            # Two keys, two different jobs, and both are needed.
                            # mockedOutput makes the trigger produce the staged
                            # event WITHOUT executing (a poll trigger would call
                            # the provider and fail on credentials);
                            # _triggerPayload is how the agent identifies WHICH
                            # trigger fired and composes the event into its turn.
                            "_triggerPayload": scenario.trigger_payload,
                            "mockedOutput": scenario.trigger_payload,
                        },
                    },
                ),
                caller_user_id=user_id,
            )
            ok = bool(getattr(result, 'success', False))
            reply = None
            node_error = None
            if ok:
                outputs = getattr(result, 'node_outputs', None) or {}
                # A CLI-harness agent may run its turn ASYNCHRONOUSLY: this run
                # only DELIVERED it to the runtime and the response lands later
                # via the turn-completion callback. Declaring the rehearsal done
                # here — and worse, tearing down the fence in `finally` — put
                # every remaining tool call of the still-live turn on the REAL
                # dispatch path. Leave the session open; the callback finishes
                # it when the turn lands, and the Redis TTL bounds a wedged run.
                if any(
                    isinstance(o, dict) and o.get('status') == 'awaiting_agent_turn'
                    for o in outputs.values()
                ):
                    finish = False
                    return
                last = getattr(result, 'last_output_node_id', None)
                out = outputs.get(last) if last else None
                reply = _reply_text(out)
                if not reply:
                    # completed != success: a run can "succeed" while its agent
                    # node errored (dead harness credential, provider outage) —
                    # which read as restraint ("Nothing to send") in the test
                    # UI, masking the failure entirely (2026-08-11, CLI agent).
                    for node_out in outputs.values():
                        if isinstance(node_out, dict) and node_out.get('error'):
                            node_error = str(node_out['error'])
                            ok = False
                            break
            else:
                logger.warning(
                    f"[rehearsal] {conversation_id} did not complete: "
                    f"{getattr(result, 'error', None)}"
                )
            # Emitted BEFORE teardown: end_rehearsal drops the state the
            # broadcast reads the watcher's user_id from.
            await emit_rehearsal_finished(
                conversation_id,
                reply if ok else None,
                None if ok else (node_error or getattr(result, 'error', None) or "the rehearsal did not complete"),
            )
        except Exception as e:
            logger.error(f"[rehearsal] run failed for {workflow_id}: {e}")
            await emit_rehearsal_finished(conversation_id, None, str(e))
        finally:
            if finish:
                await end_rehearsal(conversation_id)

    from utils.async_helpers import spawn

    spawn(_run(), name=f"rehearsal-run:{conversation_id}")
    return conversation_id, None
