"""
Skill handler — CRUD for agent-context skills.

A skill is a description + optional prose body + optional workflow body, scoped
the same way as workflows / credentials:

  * is_system = true  → platform-maintained, NULL owner_id and organization_id,
                         visible only to internal users (utils.internal_users).
  * is_system = false → owned by a user, scoped to their active org. Personal-
                         workspace orgs are real organizations (is_personal_workspace),
                         so this column covers both personal and team skills.

Sharing across users / orgs reuses the existing resource_shares table
(with 'skill' added to its resource_type CHECK constraint by the migration).

Per-user mute state lives in skill_user_mutes. System skills cannot be muted —
they are always loaded into the internal builder.

SQL lives in ``repositories/skills.py`` (``SkillRepo``); this module owns
auth composition, request parsing, and response shaping.
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from repositories.skills import SkillRepo, parse_jsonb
from utils.database_pool import DatabasePoolMixin
from utils.internal_users import is_internal_user
from wss.receiver.client_events import (
    SkillCreateRequest,
    SkillDeleteRequest,
    SkillGetRequest,
    SkillGetWorkflowRequest,
    SkillListRequest,
    SkillMuteRequest,
    SkillUpdateRequest,
    SkillUpdateWorkflowRequest,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.sender.responses import (
    SkillCreateResponse,
    SkillDeleteResponse,
    SkillDetail,
    SkillGetResponse,
    SkillListResponse,
    SkillMuteResponse,
    SkillSummary,
    SkillUpdateResponse,
    SkillUpdateWorkflowResponse,
    SkillWorkflowResponse,
)

logger = logging.getLogger(__name__)


def _row_to_summary(row: Dict[str, Any], *, muted: bool) -> SkillSummary:
    body_text = row.get("body_text")
    body_workflow = parse_jsonb(row.get("body_workflow"))
    return SkillSummary(
        id=str(row["id"]),
        owner_id=str(row["owner_id"]) if row.get("owner_id") else None,
        organization_id=str(row["organization_id"]) if row.get("organization_id") else None,
        is_system=bool(row.get("is_system")),
        name=row["name"],
        description=row.get("description") or "",
        has_text=bool(body_text and body_text.strip()),
        has_workflow=bool(body_workflow),
        enabled=bool(row.get("enabled")),
        muted=muted,
        created_at=row["created_at"].isoformat() if row.get("created_at") else "",
        updated_at=row["updated_at"].isoformat() if row.get("updated_at") else "",
    )


def _row_to_detail(row: Dict[str, Any], *, muted: bool) -> SkillDetail:
    return SkillDetail(
        id=str(row["id"]),
        owner_id=str(row["owner_id"]) if row.get("owner_id") else None,
        organization_id=str(row["organization_id"]) if row.get("organization_id") else None,
        is_system=bool(row.get("is_system")),
        name=row["name"],
        description=row.get("description") or "",
        body_text=row.get("body_text"),
        body_workflow=parse_jsonb(row.get("body_workflow")),
        display_metadata=parse_jsonb(row.get("display_metadata")) or {},
        enabled=bool(row.get("enabled")),
        muted=muted,
        created_at=row["created_at"].isoformat() if row.get("created_at") else "",
        updated_at=row["updated_at"].isoformat() if row.get("updated_at") else "",
    )


class SkillHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for skill CRUD + per-user mutes + workflow body editing."""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        return {
            "skill:list": self.list_skills,
            "skill:get": self.get_skill,
            "skill:create": self.create_skill,
            "skill:update": self.update_skill,
            "skill:delete": self.delete_skill,
            "skill:mute": self.set_mute,
            "skill:get_workflow": self.get_workflow,
            "skill:update_workflow": self.update_workflow,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    # ── Auth helpers ─────────────────────────────────────────────────────

    async def _get_auth(
        self, sid: str, request
    ) -> Tuple[Optional[str], Optional[str], Optional[SkillRepo]]:
        """Resolve (user_id, user_email, repo) or send error and return Nones."""
        session = await self.sio.get_session(sid)
        user_id = session.get("user_id") if session else None
        if not user_id:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error="User not authenticated"
            ))
            return None, None, None

        user_data = session.get("user_data", {}) if session else {}
        user_email = (user_data.get("email") or "").lower()

        pool = await self.get_pool()
        if not pool:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error="Database connection not available"
            ))
            return None, None, None

        return user_id, user_email, SkillRepo(pool)

    async def _can_view(
        self,
        repo: SkillRepo,
        user_id: str,
        skill_row: Dict[str, Any],
        *,
        is_internal: bool,
    ) -> bool:
        """Owner / internal-staff-on-system / org-member / direct-share / org-share."""
        if skill_row.get("is_system"):
            return is_internal
        if skill_row.get("owner_id") and str(skill_row["owner_id"]) == user_id:
            return True
        org_id = skill_row.get("organization_id")
        if org_id and await repo.is_org_member(user_id, org_id):
            return True
        return await repo.has_share_access(user_id, skill_row["id"], edit_only=False)

    async def _can_edit(
        self,
        repo: SkillRepo,
        user_id: str,
        skill_row: Dict[str, Any],
        *,
        is_internal: bool,
    ) -> bool:
        """Owner / internal-staff-on-system / explicit edit-permission share."""
        if skill_row.get("is_system"):
            return is_internal
        if skill_row.get("owner_id") and str(skill_row["owner_id"]) == user_id:
            return True
        # Edit shares only — org membership alone is not edit access.
        return await repo.has_share_access(user_id, skill_row["id"], edit_only=True)

    async def _send_not_found(self, sid: str, request) -> None:
        await send_event(self.sio, sid, ResponseEvent(
            request_id=request.request_id, data={}, error="Skill not found"
        ))

    # ── List ─────────────────────────────────────────────────────────────

    async def list_skills(self, sid: str, request: SkillListRequest) -> None:
        try:
            user_id, user_email, repo = await self._get_auth(sid, request)
            if not user_id:
                return

            internal = is_internal_user(user_email)

            owned_rows = await repo.list_owned_or_org(user_id)
            owned_ids = {str(r["id"]) for r in owned_rows}
            shared_rows_raw = await repo.list_shared(user_id)
            shared_rows = [r for r in shared_rows_raw if str(r["id"]) not in owned_ids]

            system_rows: List[Dict[str, Any]] = []
            if internal:
                system_rows = await repo.list_system()

            all_ids = (
                [str(r["id"]) for r in owned_rows]
                + [str(r["id"]) for r in shared_rows]
                + [str(r["id"]) for r in system_rows]
            )
            muted = await repo.muted_ids(user_id, all_ids)

            response = SkillListResponse(
                owned=[_row_to_summary(r, muted=str(r["id"]) in muted) for r in owned_rows],
                shared=[_row_to_summary(r, muted=str(r["id"]) in muted) for r in shared_rows],
                system=(
                    [_row_to_summary(r, muted=False) for r in system_rows] if internal else None
                ),
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error listing skills: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    # ── Get ──────────────────────────────────────────────────────────────

    async def get_skill(self, sid: str, request: SkillGetRequest) -> None:
        try:
            user_id, user_email, repo = await self._get_auth(sid, request)
            if not user_id:
                return
            internal = is_internal_user(user_email)

            row = await repo.load(request.skill_id)
            if not row or not await self._can_view(repo, user_id, row, is_internal=internal):
                return await self._send_not_found(sid, request)

            muted = await repo.muted_ids(user_id, [str(row["id"])])

            response = SkillGetResponse(skill=_row_to_detail(row, muted=str(row["id"]) in muted))
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error getting skill: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    # ── Create ───────────────────────────────────────────────────────────

    async def create_skill(self, sid: str, request: SkillCreateRequest) -> None:
        try:
            user_id, user_email, repo = await self._get_auth(sid, request)
            if not user_id:
                return
            internal = is_internal_user(user_email)

            if request.is_system and not internal:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="Not authorized to create system skills"
                ))
                return

            if request.is_system:
                owner_id: Optional[str] = None
                org_id: Optional[str] = None
            else:
                org_id = await repo.get_user_org_context(user_id)
                if not org_id:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={},
                        error="No active organization context",
                    ))
                    return
                owner_id = user_id

            row = await repo.create(
                owner_id=owner_id,
                organization_id=org_id,
                is_system=request.is_system,
                name=request.name,
                description=request.description or "",
                body_text=request.body_text,
                body_workflow=request.body_workflow,
                display_metadata=request.display_metadata or {},
                enabled=request.enabled,
            )

            response = SkillCreateResponse(success=True, skill=_row_to_detail(row, muted=False))
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error creating skill: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    # ── Update (metadata + body_text + enabled) ──────────────────────────

    async def update_skill(self, sid: str, request: SkillUpdateRequest) -> None:
        try:
            user_id, user_email, repo = await self._get_auth(sid, request)
            if not user_id:
                return
            internal = is_internal_user(user_email)

            row = await repo.load(request.skill_id)
            if not row or not await self._can_view(repo, user_id, row, is_internal=internal):
                return await self._send_not_found(sid, request)
            if not await self._can_edit(repo, user_id, row, is_internal=internal):
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="Edit access required"
                ))
                return

            # Only patch fields the caller actually sent.
            patches: Dict[str, Any] = {}
            for column, value in (
                ("name", request.name),
                ("description", request.description),
                ("body_text", request.body_text),
                ("enabled", request.enabled),
            ):
                if value is not None:
                    patches[column] = value

            if not patches:
                # No-op update — return current row.
                muted = await repo.muted_ids(user_id, [str(row["id"])])
                response = SkillUpdateResponse(
                    success=True,
                    skill=_row_to_detail(row, muted=str(row["id"]) in muted),
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=response.model_dump()
                ))
                return

            updated = await repo.update_metadata(request.skill_id, patches)
            muted = await repo.muted_ids(user_id, [str(updated["id"])])

            response = SkillUpdateResponse(
                success=True,
                skill=_row_to_detail(updated, muted=str(updated["id"]) in muted),
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error updating skill: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    # ── Delete ───────────────────────────────────────────────────────────

    async def delete_skill(self, sid: str, request: SkillDeleteRequest) -> None:
        try:
            user_id, user_email, repo = await self._get_auth(sid, request)
            if not user_id:
                return
            internal = is_internal_user(user_email)

            row = await repo.load(request.skill_id)
            if not row or not await self._can_view(repo, user_id, row, is_internal=internal):
                return await self._send_not_found(sid, request)

            # Only the owner may delete a non-system skill; system deletions need internal auth.
            if row.get("is_system"):
                if not internal:
                    return await self._send_not_found(sid, request)
            else:
                if str(row["owner_id"]) != user_id:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={},
                        error="Only the owner can delete this skill",
                    ))
                    return

            await repo.delete(request.skill_id)

            response = SkillDeleteResponse(success=True, message="Skill deleted")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error deleting skill: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    # ── Mute / Unmute ────────────────────────────────────────────────────

    async def set_mute(self, sid: str, request: SkillMuteRequest) -> None:
        try:
            user_id, user_email, repo = await self._get_auth(sid, request)
            if not user_id:
                return
            internal = is_internal_user(user_email)

            row = await repo.load(request.skill_id)
            if not row or not await self._can_view(repo, user_id, row, is_internal=internal):
                return await self._send_not_found(sid, request)

            if row.get("is_system"):
                # Internal users see the explicit error; non-internal got a 404 above.
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={},
                    error="System skills cannot be muted",
                ))
                return

            await repo.set_mute(request.skill_id, user_id, request.muted)

            response = SkillMuteResponse(success=True, muted=request.muted)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error setting skill mute: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    # ── Workflow body (FlowCanvas integration) ───────────────────────────

    async def get_workflow(self, sid: str, request: SkillGetWorkflowRequest) -> None:
        try:
            user_id, user_email, repo = await self._get_auth(sid, request)
            if not user_id:
                return
            internal = is_internal_user(user_email)

            row = await repo.load(request.skill_id)
            if not row or not await self._can_view(repo, user_id, row, is_internal=internal):
                return await self._send_not_found(sid, request)

            response = SkillWorkflowResponse(
                skill_id=str(row["id"]),
                body_workflow=parse_jsonb(row.get("body_workflow")),
                display_metadata=parse_jsonb(row.get("display_metadata")) or {},
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error getting skill workflow: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    async def update_workflow(self, sid: str, request: SkillUpdateWorkflowRequest) -> None:
        try:
            user_id, user_email, repo = await self._get_auth(sid, request)
            if not user_id:
                return
            internal = is_internal_user(user_email)

            row = await repo.load(request.skill_id)
            if not row or not await self._can_view(repo, user_id, row, is_internal=internal):
                return await self._send_not_found(sid, request)
            if not await self._can_edit(repo, user_id, row, is_internal=internal):
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="Edit access required"
                ))
                return

            patches: Dict[str, Any] = {}
            if request.body_workflow is not None:
                patches["body_workflow"] = request.body_workflow
            if request.display_metadata is not None:
                patches["display_metadata"] = request.display_metadata

            if patches:
                await repo.update_workflow(request.skill_id, patches)

            response = SkillUpdateWorkflowResponse(success=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error updating skill workflow: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))
