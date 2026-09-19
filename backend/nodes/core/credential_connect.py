"""Connect-time contract for manual credentials.

The one seam every surface that saves a typed-in credential goes through —
the socket ``credential:create``/``credential:update`` handlers and the public
provide link — so a key is judged the same way no matter where it was pasted.
Three layers, cheapest first:

1. **Shape.** The blob is parsed through its own credential class. Every
   string is stripped, every password-widget or key/token/secret field refuses
   a URL or placeholder text, and the class's own validators run (a pasted
   site URL becomes pod + site). Failures are per-field and nothing is saved.
2. **Prove.** The node's declared ``connection_evidence`` probe runs against
   the shaped blob BEFORE it is stored, through the node's own request helper.
   A definitive provider rejection blocks the save with the provider's words
   and a hint; "cannot judge" saves the credential as unverified. Harness LLM
   keys keep their dedicated probe (``nodes.agent.key_validation``).
3. **Show.** A saved credential answers with what was proven — the user's own
   channels, the account it signed in as — so a form can show proof instead
   of a tick, and the row remembers it (``verified_at`` / ``verified_as``).

Never blocks on a non-definitive signal (the doctrine evidence, credential
health and webhook teardown already follow): a provider outage, a timeout or
a broken probe of ours all save the credential and say it is unverified.

Adding a node costs nothing here: its credential class IS the shaping
contract and its ``connection_evidence`` IS the probe.
"""

from __future__ import annotations

import logging
import types
import typing
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel, ValidationError

from nodes.core.connection_evidence import EvidenceResult, collect_evidence as _collect_evidence
from nodes.core.credential_fields import clean_secret, looks_like_secret_field

logger = logging.getLogger(__name__)


@dataclass
class ConnectVerdict:
    """What the connect flow decided about one typed-in credential."""

    #: The blob to store — shaped by its class when one is known.
    credential_data: Dict[str, Any]
    #: Node the credential type belongs to, when the type is a node's.
    node_type: Optional[str] = None
    #: Definitive shape failures, keyed by field. Nothing is saved while set.
    field_errors: Dict[str, str] = dc_field(default_factory=dict)
    #: The provider's verbatim refusal. Nothing is saved while set.
    rejection: Optional[str] = None
    #: What the refusal usually means, when its shape says so.
    hint: Optional[str] = None
    #: The probe's answer when one ran; ``reachable`` None = unverified.
    evidence: Optional[EvidenceResult] = None

    @property
    def ok(self) -> bool:
        return not self.field_errors and not self.rejection

    @property
    def message(self) -> Optional[str]:
        """One sentence for surfaces that show a single error line."""
        if self.rejection:
            return self.rejection
        if self.field_errors:
            return next(iter(self.field_errors.values()))
        return None

    def verified_metadata(self) -> Dict[str, Any]:
        """Row metadata recording a probe that answered, for every later surface."""
        ev = self.evidence
        if ev is None or ev.reachable is not True:
            return {}
        out: Dict[str, Any] = {"verified_at": datetime.now(timezone.utc).isoformat()}
        label = ev.account_label or (ev.samples[0].label if ev.samples else None)
        if label:
            out["verified_as"] = label
        return out


# ------------------------------------------------------------ class lookup


def credential_classes_for_node(node_cls: Any) -> List[Type[BaseModel]]:
    """The credential classes a node's config model accepts, from its annotation.

    ``NodeConfig[ConfigT, CredentialT]`` types ``credentials`` as an optional
    union of credential classes; this walks that union so the classes come
    from the one place the runtime parses them, never from a hand list.
    """
    getter = getattr(node_cls, "get_config_model", None)
    model = getter() if callable(getter) else None
    if model is None:
        return []
    out: List[Type[BaseModel]] = []

    def walk(t: Any) -> None:
        origin = typing.get_origin(t)
        if origin is typing.Union or origin is types.UnionType:
            for arg in typing.get_args(t):
                walk(arg)
        elif origin is typing.Annotated:
            walk(typing.get_args(t)[0])
        elif isinstance(t, type) and issubclass(t, BaseModel) and t not in out:
            out.append(t)

    candidates = typing.get_args(model) if typing.get_origin(model) in (typing.Union, types.UnionType) else (model,)
    for candidate in candidates:
        fld = getattr(candidate, "model_fields", {}).get("credentials")
        if fld is not None:
            walk(fld.annotation)
    return out


def credential_type_of(cls: Type[BaseModel]) -> Optional[str]:
    """The ``credential_type`` literal a credential class is pinned to."""
    fld = cls.model_fields.get("credential_type")
    if fld is None:
        return None
    if isinstance(fld.default, str):
        return fld.default
    args = typing.get_args(fld.annotation)
    return args[0] if args and isinstance(args[0], str) else None


@lru_cache(maxsize=1)
def _class_index() -> Dict[str, Tuple[str, Type[BaseModel]]]:
    from nodes.core.registry import NODE_REGISTRY

    index: Dict[str, Tuple[str, Type[BaseModel]]] = {}
    for node_type, node_cls in NODE_REGISTRY.items():
        for cls in credential_classes_for_node(node_cls):
            ct = credential_type_of(cls)
            if ct and ct not in index:
                index[ct] = (node_type, cls)
    return index


def resolve_credential_class(credential_type: Optional[str]) -> Optional[Tuple[str, Type[BaseModel]]]:
    """``(node_type, credential class)`` for a stored ``credential_type``, or None.

    Credential types are unique per node, so this is a lookup, not a search.
    None covers types no node declares (agent OAuth sign-ins, legacy rows),
    which shape as-is.
    """
    return _class_index().get(credential_type or "")


# ----------------------------------------------------------------- shaping


def _secret_fields(cls: Type[BaseModel]) -> Dict[str, str]:
    """Field name -> title for the fields that hold a secret."""
    out: Dict[str, str] = {}
    for name, fld in cls.model_fields.items():
        if name == "credential_type":
            continue
        extra = fld.json_schema_extra if isinstance(fld.json_schema_extra, dict) else {}
        if extra.get("ui:widget") == "password" or looks_like_secret_field(name):
            out[name] = fld.title or name.replace("_", " ").capitalize()
    return out


def _human_error(cls: Type[BaseModel], name: str, err: Dict[str, Any]) -> str:
    fld = cls.model_fields.get(name)
    label = (fld.title if fld is not None and fld.title else name.replace("_", " ").capitalize())
    kind = err.get("type") or ""
    msg = err.get("msg") or "Invalid value"
    if kind == "missing":
        return f"{label} is required."
    for prefix in ("Value error, ", "Assertion failed, "):
        if msg.startswith(prefix):
            return msg[len(prefix):]
    expected = (err.get("ctx") or {}).get("expected")
    if kind in ("literal_error", "enum") and expected:
        return f"{label} must be one of: {expected}."
    return f"{label}: {msg}"


def shape_credential(
    credential_type: Optional[str], credential_data: Optional[Dict[str, Any]]
) -> Tuple[Dict[str, Any], Dict[str, str], Optional[Tuple[str, Type[BaseModel]]]]:
    """``(shaped blob, field errors, resolved class)`` — layer 1, no network.

    Keys the class does not declare survive untouched (a blob may carry
    surface-specific extras); declared fields come back normalised by the
    class's validators. With errors the blob is returned as typed so a form can
    re-show it.
    """
    data: Dict[str, Any] = {
        k: (v.strip() if isinstance(v, str) else v) for k, v in (credential_data or {}).items()
    }
    resolved = resolve_credential_class(credential_type)
    if resolved is None:
        return data, {}, None
    _, cls = resolved

    errors: Dict[str, str] = {}
    for name, title in _secret_fields(cls).items():
        value = data.get(name)
        if isinstance(value, str) and value:
            try:
                data[name] = clean_secret(value, field_name=title)
            except ValueError as e:
                errors[name] = str(e)
    if errors:
        return data, errors, resolved

    try:
        model = cls.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            loc = err.get("loc") or ()
            name = str(loc[0]) if loc else "_"
            errors.setdefault(name, _human_error(cls, name, err))
        return data, errors, resolved

    shaped = model.model_dump(mode="json", exclude_unset=True)
    return {**data, **shaped}, {}, resolved


# ----------------------------------------------------------------- verdict


async def _validate_agent_api_key(credential_type: Optional[str], credential_data: Any) -> Optional[str]:
    """Harness-key probe behind a module attribute, for the same reason as
    ``_collect_evidence``: it talks to real providers and the test suite stubs it."""
    from nodes.agent.key_validation import validate_agent_api_key

    return await validate_agent_api_key(credential_type, credential_data)


async def validate_for_connect(
    *,
    credential_type: Optional[str],
    credential_data: Optional[Dict[str, Any]],
    user_id: str,
    pool=None,
    organization_id: Optional[str] = None,
    probe: bool = True,
) -> ConnectVerdict:
    """Judge a typed-in credential before it is stored.

    ``probe=False`` runs shaping only (surfaces that must not wait on a
    provider). Never raises for a provider's sake: only our own bugs propagate.
    """
    if (credential_type or "").startswith("agent"):
        # Harness credentials are {"credentials": {ENV: value}} bundles with
        # their own provider probes; key_validation owns both.
        rejection = await _validate_agent_api_key(credential_type, credential_data) if probe else None
        return ConnectVerdict(credential_data=dict(credential_data or {}), rejection=rejection)

    shaped, errors, resolved = shape_credential(credential_type, credential_data)
    verdict = ConnectVerdict(
        credential_data=shaped,
        field_errors=errors,
        node_type=resolved[0] if resolved else None,
    )
    if errors or not probe or resolved is None:
        return verdict

    from nodes.core.registry import NODE_REGISTRY

    node_type = resolved[0]
    if getattr(NODE_REGISTRY.get(node_type), "connection_evidence", None) is None:
        return verdict

    # Module attribute on purpose: it is the seam the test suite stubs so a
    # create in a test never reaches a real provider (tests/conftest.py).
    result = await _collect_evidence(
        node_type=node_type,
        credential_data=shaped,
        user_id=user_id,
        pool=pool,
        organization_id=organization_id,
    )
    verdict.evidence = result
    if result.reachable is False:
        verdict.rejection = result.error or "The provider rejected this credential."
        verdict.hint = result.hint
        logger.info("[credential_connect] %s rejected at connect time", credential_type)
    return verdict
