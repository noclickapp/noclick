"""
Test suite for workflow invite links (the collaborative share-link loop) against
a real PostgreSQL database.

Validates:
- Minting is personal-workflow-only and idempotent; CREATE is owner-only, but
  any collaborator WITH access can FETCH the existing link (the viral re-share loop)
- Users with no access, and organization workflows, are rejected
- Redeeming a link grants the joiner an 'edit' direct-share on the SAME workflow
  (the row check_resource_access / collab tokens already understand)
- The owner redeeming their own link is a no-op (no self-share)
- Invalid / inactive tokens are rejected
"""

import pytest
import pytest_asyncio
import asyncio
import json
import uuid
from typing import Dict, Any

from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database
from wss.receiver.client_events import (
    ShareInviteLinkRequest,
    ShareInviteAcceptRequest,
    CredentialDisplayInfoRequest,
    CredentialAuthorizeForWorkflowRequest,
)
from wss.sender import send_event


SESSION_USER_ID = '00000000-0000-4000-8000-000000000001'
OTHER_OWNER_ID = '00000000-0000-4000-8000-000000000099'


@pytest.mark.asyncio
class TestWorkflowInviteLinks(BaseHandlerTest):
    """Integration tests for share:invite_link and share:invite_accept."""

    def get_session_data(self, sid: str) -> Dict[str, Any]:
        return {
            'sid': sid,
            'user_id': SESSION_USER_ID,
            'email': 'invite-test@example.com',
            'user_data': {
                'email': 'invite-test@example.com',
                'subscription_tier': 'enterprise',
            },
        }

    async def create_test_user(self, real_database, user_id: str, email: str):
        await real_database.execute(
            "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
            user_id, email,
        )

    async def create_test_organization(self, real_database, org_id: str, name: str, owner_id: str, is_personal_workspace: bool = False):
        await real_database.execute(
            "INSERT INTO organizations (id, name, slug, is_personal_workspace) VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO NOTHING",
            org_id, name, name.lower().replace(' ', '-'), is_personal_workspace,
        )
        await real_database.execute(
            "INSERT INTO organization_members (organization_id, user_id, role) "
            "VALUES ($1, $2, 'owner') ON CONFLICT (organization_id, user_id) DO NOTHING",
            org_id, owner_id,
        )

    async def create_test_workflow(self, real_database, workflow_id: str, owner_id: str, name: str, org_id: str = None, workflow_blob: dict = None):
        await real_database.execute(
            """
            INSERT INTO workflows (id, owner_id, organization_id, name, description, workflow, permissions, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
            ON CONFLICT (id) DO NOTHING
            """,
            workflow_id, owner_id, org_id, name, "Test workflow", workflow_blob or {}, {},
        )

    async def insert_credential(self, real_database, cred_id: str, owner_id: str, credential_type: str = 'api_key', name: str = 'Test Cred'):
        await real_database.execute(
            "INSERT INTO credentials (id, owner_id, name, credential_type, credential) VALUES ($1, $2, $3, $4, $5)",
            cred_id, owner_id, name, credential_type, 'encrypted-test-blob',
        )

    def workflow_with_cred_node(self, cred_id: str, credential_type: str = 'api_key') -> dict:
        """A workflow blob whose single node sets `cred_id` on credentialIds."""
        return {
            "nodes": [{"id": "node-1", "type": "automation-slack", "data": {"credentialIds": {credential_type: cred_id}}}],
            "edges": [],
        }

    async def insert_invite_link(self, real_database, workflow_id: str, token: str, created_by: str, permission: str = 'edit'):
        await real_database.execute(
            """
            INSERT INTO workflow_invite_links (workflow_id, token, permission, created_by)
            VALUES ($1, $2, $3, $4)
            """,
            workflow_id, token, permission, created_by,
        )

    async def insert_resource_share(self, real_database, workflow_id: str, target_user_id: str, shared_by: str, permission: str = 'edit'):
        await real_database.execute(
            """
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by)
            VALUES ('workflow', $1, 'user', $2, $3, $4)
            """,
            workflow_id, target_user_id, permission, shared_by,
        )

    def _response_for(self, request_id: str):
        events = self.get_main_api_emitted_events("response")
        return [e for e in events if e[1].get('request_id') == request_id]

    # ==================== MINT ====================

    async def test_create_invite_link_mints_token(self, real_database, frontend_sio, sid):
        """Owner of a personal workflow mints a fresh, persisted 'edit' link."""
        workflow_id = str(uuid.uuid4())
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_workflow(real_database, workflow_id, SESSION_USER_ID, "My Flow")
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, ShareInviteLinkRequest(
            event_name="share:invite_link", request_id="mint-1", workflow_id=workflow_id,
        ))
        await asyncio.sleep(0.2)

        matching = self._response_for("mint-1")
        assert len(matching) == 1
        data = matching[0][1]['data']
        assert data.get('success') is True
        assert data.get('token')
        assert data.get('permission') == 'edit'
        assert data.get('url', '').endswith(data['token'])

        row = await real_database.fetchrow(
            "SELECT workflow_id, permission, is_active FROM workflow_invite_links WHERE token = $1",
            data['token'],
        )
        assert row is not None
        assert str(row['workflow_id']) == workflow_id
        assert row['permission'] == 'edit'
        assert row['is_active'] is True

    async def test_create_invite_link_idempotent(self, real_database, frontend_sio, sid):
        """Re-minting returns the SAME token and keeps exactly one active link."""
        workflow_id = str(uuid.uuid4())
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_workflow(real_database, workflow_id, SESSION_USER_ID, "My Flow")
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, ShareInviteLinkRequest(
            event_name="share:invite_link", request_id="mint-a", workflow_id=workflow_id,
        ))
        await asyncio.sleep(0.2)
        await send_event(frontend_sio, sid, ShareInviteLinkRequest(
            event_name="share:invite_link", request_id="mint-b", workflow_id=workflow_id,
        ))
        await asyncio.sleep(0.2)

        token_a = self._response_for("mint-a")[0][1]['data']['token']
        token_b = self._response_for("mint-b")[0][1]['data']['token']
        assert token_a == token_b

        rows = await real_database.fetch(
            "SELECT id FROM workflow_invite_links WHERE workflow_id = $1 AND is_active = true",
            workflow_id,
        )
        assert len(rows) == 1

    async def test_create_invite_link_rejects_non_collaborator(self, real_database, frontend_sio, sid):
        """A user with NO access to the workflow can't fetch or mint its link."""
        workflow_id = str(uuid.uuid4())
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_user(real_database, OTHER_OWNER_ID, 'owner@example.com')
        await self.create_test_workflow(real_database, workflow_id, OTHER_OWNER_ID, "Not Mine")
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, ShareInviteLinkRequest(
            event_name="share:invite_link", request_id="mint-deny", workflow_id=workflow_id,
        ))
        await asyncio.sleep(0.2)

        response = self._response_for("mint-deny")[0][1]
        assert 'error' in response
        assert 'access' in response['error'].lower()

    async def test_create_invite_link_collaborator_fetches_existing(self, real_database, frontend_sio, sid):
        """A non-owner WITH an edit share fetches the owner's existing active link
        (so collaborators can re-share it) — without minting a second link."""
        workflow_id = str(uuid.uuid4())
        token = "collab-fetch-token"
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_user(real_database, OTHER_OWNER_ID, 'owner@example.com')
        await self.create_test_workflow(real_database, workflow_id, OTHER_OWNER_ID, "Shared Flow")
        # Owner already minted the link; the session user is a collaborator.
        await self.insert_invite_link(real_database, workflow_id, token, OTHER_OWNER_ID)
        await self.insert_resource_share(real_database, workflow_id, SESSION_USER_ID, OTHER_OWNER_ID)
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, ShareInviteLinkRequest(
            event_name="share:invite_link", request_id="collab-fetch", workflow_id=workflow_id,
        ))
        await asyncio.sleep(0.2)

        data = self._response_for("collab-fetch")[0][1]['data']
        assert data.get('success') is True
        assert data.get('token') == token  # SAME existing token, not a new one
        rows = await real_database.fetch(
            "SELECT id FROM workflow_invite_links WHERE workflow_id = $1 AND is_active = true",
            workflow_id,
        )
        assert len(rows) == 1  # collaborator did NOT create a second link

    async def test_create_invite_link_collaborator_cannot_create(self, real_database, frontend_sio, sid):
        """A collaborator can't CREATE the link (owner-only). With no active link
        they get a clear 'unavailable', and none is created on their behalf."""
        workflow_id = str(uuid.uuid4())
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_user(real_database, OTHER_OWNER_ID, 'owner@example.com')
        await self.create_test_workflow(real_database, workflow_id, OTHER_OWNER_ID, "Shared Flow 2")
        await self.insert_resource_share(real_database, workflow_id, SESSION_USER_ID, OTHER_OWNER_ID)
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, ShareInviteLinkRequest(
            event_name="share:invite_link", request_id="collab-none", workflow_id=workflow_id,
        ))
        await asyncio.sleep(0.2)

        response = self._response_for("collab-none")[0][1]
        assert 'error' in response
        rows = await real_database.fetch(
            "SELECT id FROM workflow_invite_links WHERE workflow_id = $1",
            workflow_id,
        )
        assert len(rows) == 0  # owner-only creation: nothing minted for the collaborator

    async def test_create_invite_link_rejects_org_workflow(self, real_database, frontend_sio, sid):
        """Invite links are disabled for org-owned workflows in v1."""
        org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_organization(real_database, org_id, "Acme", SESSION_USER_ID)
        await self.create_test_workflow(real_database, workflow_id, SESSION_USER_ID, "Org Flow", org_id)
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, ShareInviteLinkRequest(
            event_name="share:invite_link", request_id="mint-org", workflow_id=workflow_id,
        ))
        await asyncio.sleep(0.2)

        response = self._response_for("mint-org")[0][1]
        assert 'error' in response
        assert 'organization' in response['error'].lower()

    async def test_create_invite_link_allows_personal_workspace_workflow(self, real_database, frontend_sio, sid):
        """A personal workspace is backed by a real org row (is_personal_workspace=true),
        but it is NOT an organization workflow — minting must succeed (regression: the
        non-null organization_id was wrongly treated as an org workflow)."""
        org_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_organization(real_database, org_id, "My Personal WS", SESSION_USER_ID, is_personal_workspace=True)
        await self.create_test_workflow(real_database, workflow_id, SESSION_USER_ID, "Personal WS Flow", org_id)
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, ShareInviteLinkRequest(
            event_name="share:invite_link", request_id="mint-personal-ws", workflow_id=workflow_id,
        ))
        await asyncio.sleep(0.2)

        response = self._response_for("mint-personal-ws")[0][1]
        assert not response.get('error'), response
        assert response['data'].get('token'), "personal-workspace workflow must mint a link"

    # ==================== ACCEPT ====================

    async def test_accept_invite_grants_edit_share(self, real_database, frontend_sio, sid):
        """Redeeming writes an 'edit' direct-share for the joiner, shared_by owner."""
        workflow_id = str(uuid.uuid4())
        token = "test-token-accept-edit"
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_user(real_database, OTHER_OWNER_ID, 'owner@example.com')
        await self.create_test_workflow(real_database, workflow_id, OTHER_OWNER_ID, "Owner's Flow")
        await self.insert_invite_link(real_database, workflow_id, token, OTHER_OWNER_ID)
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, ShareInviteAcceptRequest(
            event_name="share:invite_accept", request_id="accept-1", token=token,
        ))
        await asyncio.sleep(0.2)

        data = self._response_for("accept-1")[0][1]['data']
        assert data.get('success') is True
        assert data.get('workflow_id') == workflow_id
        assert data.get('workflow_name') == "Owner's Flow"
        # Joiner gets onboarded by the redeem → frontend told to refresh the JWT.
        assert data.get('refresh_jwt') is True

        share = await real_database.fetchrow(
            """
            SELECT target_user_id, permission, shared_by FROM resource_shares
            WHERE resource_type = 'workflow' AND resource_id = $1 AND target_type = 'user'
            """,
            workflow_id,
        )
        assert share is not None
        assert str(share['target_user_id']) == SESSION_USER_ID
        assert share['permission'] == 'edit'
        assert str(share['shared_by']) == OTHER_OWNER_ID

        # Onboarding row created (skips the questionnaire) with the referral sentinel.
        ob = await real_database.fetchrow(
            "SELECT responses FROM user_onboarding_responses WHERE user_id = $1", SESSION_USER_ID
        )
        assert ob is not None
        resp = ob['responses']
        if isinstance(resp, str):
            resp = json.loads(resp)
        assert resp.get('how_did_you_hear') == 'referral'
        assert resp.get('referred_by') == OTHER_OWNER_ID
        assert resp.get('referred_via_workflow') == workflow_id
        assert resp.get('invite_token') == token

        # Referral lineage recorded.
        red = await real_database.fetchrow(
            "SELECT inviter_id, redeemer_id, workflow_id FROM invite_redemptions WHERE invite_token = $1",
            token,
        )
        assert red is not None
        assert str(red['inviter_id']) == OTHER_OWNER_ID
        assert str(red['redeemer_id']) == SESSION_USER_ID
        assert str(red['workflow_id']) == workflow_id

    async def test_accept_invite_owner_is_noop(self, real_database, frontend_sio, sid):
        """The owner opening their own link gets the workflow back but no self-share."""
        workflow_id = str(uuid.uuid4())
        token = "test-token-owner-noop"
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_workflow(real_database, workflow_id, SESSION_USER_ID, "My Own Flow")
        await self.insert_invite_link(real_database, workflow_id, token, SESSION_USER_ID)
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, ShareInviteAcceptRequest(
            event_name="share:invite_accept", request_id="accept-owner", token=token,
        ))
        await asyncio.sleep(0.2)

        data = self._response_for("accept-owner")[0][1]['data']
        assert data.get('success') is True
        assert data.get('workflow_id') == workflow_id
        # Owner opening their own link is a no-op: no onboarding change, no refresh.
        assert data.get('refresh_jwt') is False

        shares = await real_database.fetch(
            "SELECT id FROM resource_shares WHERE resource_id = $1 AND target_type = 'user'",
            workflow_id,
        )
        assert len(shares) == 0

        # No lineage recorded for the owner's own-link redemption (token-scoped,
        # so unaffected by other tests' shared DB state).
        red = await real_database.fetch("SELECT id FROM invite_redemptions WHERE invite_token = $1", token)
        assert len(red) == 0

    async def test_accept_invite_idempotent(self, real_database, frontend_sio, sid):
        """Re-accepting the same link upserts (no duplicate share rows)."""
        workflow_id = str(uuid.uuid4())
        token = "test-token-accept-twice"
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_user(real_database, OTHER_OWNER_ID, 'owner@example.com')
        await self.create_test_workflow(real_database, workflow_id, OTHER_OWNER_ID, "Owner's Flow")
        await self.insert_invite_link(real_database, workflow_id, token, OTHER_OWNER_ID)
        await asyncio.sleep(0.1)

        for rid in ("accept-x", "accept-y"):
            await send_event(frontend_sio, sid, ShareInviteAcceptRequest(
                event_name="share:invite_accept", request_id=rid, token=token,
            ))
            await asyncio.sleep(0.2)

        assert self._response_for("accept-y")[0][1]['data'].get('success') is True
        shares = await real_database.fetch(
            "SELECT id FROM resource_shares WHERE resource_id = $1 AND target_type = 'user'",
            workflow_id,
        )
        assert len(shares) == 1
        # Lineage is recorded exactly once across re-accepts.
        red = await real_database.fetch("SELECT id FROM invite_redemptions WHERE invite_token = $1", token)
        assert len(red) == 1

    async def test_accept_invite_invalid_token(self, real_database, frontend_sio, sid):
        """An unknown / inactive token is rejected."""
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, ShareInviteAcceptRequest(
            event_name="share:invite_accept", request_id="accept-bad", token="nonexistent-token",
        ))
        await asyncio.sleep(0.2)

        response = self._response_for("accept-bad")[0][1]
        assert 'error' in response
        assert 'no longer valid' in response['error'].lower()

    # ==================== NODE CREDENTIALS (run-as-owner model) ====================

    async def test_accept_invite_does_not_share_credentials(self, real_database, frontend_sio, sid):
        """Joining must NOT create credential resource_shares. The flow's node
        credentials are resolved as the workflow OWNER at execution (so a
        collaborator can run them) without the credential ever being copied into
        the collaborator's account — which would let them use it elsewhere."""
        workflow_id = str(uuid.uuid4())
        cred_id = str(uuid.uuid4())
        token = "test-token-no-cred-share"
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_user(real_database, OTHER_OWNER_ID, 'owner@example.com')
        await self.insert_credential(real_database, cred_id, OTHER_OWNER_ID)
        await self.create_test_workflow(
            real_database, workflow_id, OTHER_OWNER_ID, "Shared Flow",
            workflow_blob=self.workflow_with_cred_node(cred_id),
        )
        await self.insert_invite_link(real_database, workflow_id, token, OTHER_OWNER_ID)
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, ShareInviteAcceptRequest(
            event_name="share:invite_accept", request_id="accept-nocred", token=token,
        ))
        await asyncio.sleep(0.3)

        # The joiner DOES get the workflow share (edit access)...
        wf_share = await real_database.fetchrow(
            "SELECT id FROM resource_shares WHERE resource_type = 'workflow' AND resource_id = $1 AND target_user_id = $2",
            workflow_id, SESSION_USER_ID,
        )
        assert wf_share is not None, "joiner should get the workflow share"
        # ...but NO credential share is created — the cred stays the owner's.
        cred_share = await real_database.fetchrow(
            "SELECT id FROM resource_shares WHERE resource_type = 'credential' AND resource_id = $1 AND target_user_id = $2",
            cred_id, SESSION_USER_ID,
        )
        assert cred_share is None, "joining must NOT copy the owner's credential into the collaborator's account"

    # ==================== DISPLAY INFO ====================

    async def _set_user_name(self, real_database, user_id: str, name: str):
        await real_database.execute(
            "UPDATE auth.users SET raw_user_meta_data = jsonb_build_object('name', $2::text) WHERE id = $1",
            user_id, name,
        )

    async def test_display_info_shows_owner_tag_for_collaborator(self, real_database, frontend_sio, sid):
        """A collaborator on a shared workflow can SEE the name + owner of a
        credential the flow uses (so the 'owned by' tag renders), without the
        credential being shared into their account and without leaking the secret."""
        workflow_id = str(uuid.uuid4())
        cred_id = str(uuid.uuid4())
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_user(real_database, OTHER_OWNER_ID, 'owner@example.com')
        await self._set_user_name(real_database, OTHER_OWNER_ID, 'Owner McOwner')
        await self.insert_credential(real_database, cred_id, OTHER_OWNER_ID, name='Prod Slack')
        await self.create_test_workflow(
            real_database, workflow_id, OTHER_OWNER_ID, "Shared Flow",
            workflow_blob=self.workflow_with_cred_node(cred_id),
        )
        await self.insert_resource_share(real_database, workflow_id, SESSION_USER_ID, OTHER_OWNER_ID)
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, CredentialDisplayInfoRequest(
            event_name="credential:display_info", request_id="disp-1", workflow_id=workflow_id,
        ))
        await asyncio.sleep(0.2)

        response = self._response_for("disp-1")[0][1]
        assert not response.get('error'), response
        creds = response['data']['credentials']
        assert len(creds) == 1, creds
        c = creds[0]
        assert c['id'] == cred_id
        assert c['name'] == 'Prod Slack'
        assert c['owned_by_me'] is False
        assert c['owner_name'] == 'Owner McOwner'
        # display-only: the secret blob is never returned
        assert 'credential' not in c and 'data' not in c

    async def test_display_info_owner_sees_no_owner_tag(self, real_database, frontend_sio, sid):
        """The owner viewing their own flow sees owned_by_me=True and NO owner tag."""
        workflow_id = str(uuid.uuid4())
        cred_id = str(uuid.uuid4())
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.insert_credential(real_database, cred_id, SESSION_USER_ID, name='My Key')
        await self.create_test_workflow(
            real_database, workflow_id, SESSION_USER_ID, "My Flow",
            workflow_blob=self.workflow_with_cred_node(cred_id),
        )
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, CredentialDisplayInfoRequest(
            event_name="credential:display_info", request_id="disp-2", workflow_id=workflow_id,
        ))
        await asyncio.sleep(0.2)

        response = self._response_for("disp-2")[0][1]
        assert not response.get('error'), response
        creds = response['data']['credentials']
        assert len(creds) == 1, creds
        assert creds[0]['owned_by_me'] is True
        assert creds[0]['owner_name'] is None

    async def test_display_info_denied_without_workflow_access(self, real_database, frontend_sio, sid):
        """Without workflow access, display_info returns NO credential metadata —
        it can't be used to enumerate someone else's credential names."""
        workflow_id = str(uuid.uuid4())
        cred_id = str(uuid.uuid4())
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_user(real_database, OTHER_OWNER_ID, 'owner@example.com')
        await self.insert_credential(real_database, cred_id, OTHER_OWNER_ID, name='Secret Key')
        await self.create_test_workflow(
            real_database, workflow_id, OTHER_OWNER_ID, "Not Shared",
            workflow_blob=self.workflow_with_cred_node(cred_id),
        )
        # NO resource_share for SESSION_USER_ID
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, CredentialDisplayInfoRequest(
            event_name="credential:display_info", request_id="disp-3", workflow_id=workflow_id,
        ))
        await asyncio.sleep(0.2)

        response = self._response_for("disp-3")[0][1]
        assert response.get('error'), response
        assert 'access' in response['error'].lower()

    async def test_display_info_excludes_third_party_credential(self, real_database, frontend_sio, sid):
        """display_info is scoped to credentials owned by the WORKFLOW OWNER. A
        collaborator can't slip a third party's credential UUID onto a node and read
        back that third party's credential name + owner identity."""
        third_user_id = '00000000-0000-4000-8000-000000000077'
        workflow_id = str(uuid.uuid4())
        third_cred = str(uuid.uuid4())
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_user(real_database, OTHER_OWNER_ID, 'owner@example.com')
        await self.create_test_user(real_database, third_user_id, 'victim@example.com')
        # The credential belongs to a THIRD user, not the workflow owner.
        await self.insert_credential(real_database, third_cred, third_user_id, name='Victim Secret')
        await self.create_test_workflow(
            real_database, workflow_id, OTHER_OWNER_ID, "Shared Flow",
            workflow_blob=self.workflow_with_cred_node(third_cred),
        )
        await self.insert_resource_share(real_database, workflow_id, SESSION_USER_ID, OTHER_OWNER_ID)
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, CredentialDisplayInfoRequest(
            event_name="credential:display_info", request_id="disp-3p", workflow_id=workflow_id,
        ))
        await asyncio.sleep(0.2)

        response = self._response_for("disp-3p")[0][1]
        assert not response.get('error'), response
        creds = response['data']['credentials']
        assert all(c['id'] != third_cred for c in creds), "third party's credential must not leak"

    async def test_accept_invite_rejects_link_not_minted_by_owner(self, real_database, frontend_sio, sid):
        """Defense in depth: a link whose creator is not the workflow owner (e.g. one
        forged directly via a mis-scoped RLS path) is rejected at redemption and grants
        no access."""
        workflow_id = str(uuid.uuid4())
        token = "forged-link-token"
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_user(real_database, OTHER_OWNER_ID, 'owner@example.com')
        await self.create_test_workflow(real_database, workflow_id, OTHER_OWNER_ID, "Victim Flow")
        # Forged: created_by is the attacker (SESSION_USER), not the workflow owner.
        await self.insert_invite_link(real_database, workflow_id, token, SESSION_USER_ID)
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, ShareInviteAcceptRequest(
            event_name="share:invite_accept", request_id="accept-forged", token=token,
        ))
        await asyncio.sleep(0.2)

        response = self._response_for("accept-forged")[0][1]
        assert response.get('error'), response
        share = await real_database.fetchrow(
            "SELECT id FROM resource_shares WHERE resource_id = $1 AND target_user_id = $2",
            workflow_id, SESSION_USER_ID,
        )
        assert share is None, "a forged (non-owner) link must not grant access"

    # ==================== CREDENTIAL AUTHORIZE (explicit owner-pick) ====================

    async def test_authorize_for_workflow_owner_authorizes(self, real_database, frontend_sio, sid):
        """The owner explicitly picking a credential authorizes it for run-as-owner
        resolution — the trusted signal that the (presence-tainted) autosave no longer
        provides."""
        workflow_id = str(uuid.uuid4())
        cred_id = str(uuid.uuid4())
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.insert_credential(real_database, cred_id, SESSION_USER_ID)
        await self.create_test_workflow(real_database, workflow_id, SESSION_USER_ID, "My Flow")
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, CredentialAuthorizeForWorkflowRequest(
            event_name="credential:authorize_for_workflow", request_id="authz-1",
            workflow_id=workflow_id, credential_id=cred_id,
        ))
        await asyncio.sleep(0.2)

        response = self._response_for("authz-1")[0][1]
        assert not response.get('error'), response
        assert response['data']['authorized'] is True
        row = await real_database.fetchrow(
            "SELECT authorized_by FROM workflow_authorized_credentials WHERE workflow_id = $1 AND credential_id = $2",
            workflow_id, cred_id,
        )
        assert row is not None, "owner-picked credential must be authorized"
        assert str(row['authorized_by']) == SESSION_USER_ID

    async def test_authorize_for_workflow_collaborator_is_noop(self, real_database, frontend_sio, sid):
        """A COLLABORATOR calling authorize is a silent no-op — they can't introduce an
        owner credential into the authorized set (this is the exfiltration guard)."""
        workflow_id = str(uuid.uuid4())
        cred_id = str(uuid.uuid4())
        await self.create_test_user(real_database, SESSION_USER_ID, 'invite-test@example.com')
        await self.create_test_user(real_database, OTHER_OWNER_ID, 'owner@example.com')
        # Credential + workflow both belong to the OWNER; SESSION_USER is just a collaborator.
        await self.insert_credential(real_database, cred_id, OTHER_OWNER_ID, name='Owner Secret')
        await self.create_test_workflow(real_database, workflow_id, OTHER_OWNER_ID, "Shared Flow")
        await self.insert_resource_share(real_database, workflow_id, SESSION_USER_ID, OTHER_OWNER_ID)
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, CredentialAuthorizeForWorkflowRequest(
            event_name="credential:authorize_for_workflow", request_id="authz-2",
            workflow_id=workflow_id, credential_id=cred_id,
        ))
        await asyncio.sleep(0.2)

        response = self._response_for("authz-2")[0][1]
        assert not response.get('error'), response
        assert response['data']['authorized'] is False
        row = await real_database.fetchrow(
            "SELECT credential_id FROM workflow_authorized_credentials WHERE workflow_id = $1 AND credential_id = $2",
            workflow_id, cred_id,
        )
        assert row is None, "a collaborator must not be able to authorize an owner credential"
