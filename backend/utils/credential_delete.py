"""Deleting a credential: provider-side teardown first, then the row.

The one deletion path for every surface that deletes a credential. Teardown
needs the still-valid credential, so trigger webhooks registered under it are
deregistered and provider grants revoked BEFORE the row goes; a failed
teardown is logged and the delete proceeds (the deactivated webhook row 410s
deliveries either way).
"""

import logging
from typing import Dict, List

from nodes.oauth.google_oauth import revoke_token as revoke_google_token
from nodes.oauth.klaviyo_oauth import revoke_token as revoke_klaviyo_token
from nodes.oauth.twitter_oauth import revoke_token as revoke_twitter_token
from repositories.credentials import CredentialsRepo
from utils.encryption import get_encryption
from utils.webhook_manager import WebhookManager

logger = logging.getLogger(__name__)


async def delete_credential_with_teardown(pool, row, *, credential_id: str, user_id: str) -> None:
    """Tear down and delete a credential the caller already proved it owns
    (``row`` is ``CredentialsRepo.fetch_for_delete_as_owner``'s answer)."""
    repo = CredentialsRepo(pool)
    webhook_nodes = await repo.list_active_webhook_nodes_for_credential(credential_id)
    nodes_by_workflow: Dict[str, List[str]] = {}
    for ref in webhook_nodes:
        nodes_by_workflow.setdefault(ref["workflow_id"], []).append(ref["node_id"])
    for wf_id, node_ids in nodes_by_workflow.items():
        try:
            await WebhookManager.deregister_node_webhooks(
                pool, wf_id, node_ids, requesting_user_id=user_id,
            )
        except Exception as e:
            logger.error(
                f"[CredentialDelete] Webhook deregistration failed for "
                f"workflow {wf_id} nodes {node_ids} during credential delete: {e}"
            )

    credential_type = row.credential_type
    if credential_type and credential_type.startswith('google'):
        try:
            cred_data = get_encryption().decrypt_credential(row.credential)
            # Revoking the refresh token also invalidates access tokens.
            if 'refresh_token' in cred_data:
                await revoke_google_token(cred_data['refresh_token'])
                logger.info(f"[CredentialDelete] Revoked Google token for credential {credential_id}")
        except Exception as e:
            logger.warning(f"[CredentialDelete] Failed to revoke Google token: {e}")

    if credential_type == 'twitter_oauth':
        try:
            cred_data = get_encryption().decrypt_credential(row.credential)
            if cred_data.get('refresh_token'):
                await revoke_twitter_token(
                    cred_data['refresh_token'],
                    token_type_hint="refresh_token",
                    client_id=cred_data.get('client_id'),
                    client_secret=cred_data.get('client_secret'),
                )
                logger.info(f"[CredentialDelete] Revoked Twitter token for credential {credential_id}")
        except Exception as e:
            logger.warning(f"[CredentialDelete] Failed to revoke Twitter token: {e}")

    # Revoking the grant uninstalls the app on Klaviyo's side (marketplace uninstall).
    if credential_type == 'klaviyo_oauth':
        try:
            cred_data = get_encryption().decrypt_credential(row.credential)
            if cred_data.get('refresh_token'):
                await revoke_klaviyo_token(
                    cred_data['refresh_token'],
                    token_type_hint="refresh_token",
                    client_id=cred_data.get('client_id'),
                    client_secret=cred_data.get('client_secret'),
                )
                logger.info(f"[CredentialDelete] Revoked Klaviyo token for credential {credential_id}")
        except Exception as e:
            logger.warning(f"[CredentialDelete] Failed to revoke Klaviyo token: {e}")

    # A live WAHooks connection with no credential is billed AND still linked to
    # the user's WhatsApp, so a failed teardown is an ERROR (the daily orphan
    # sweep reconciles).
    if credential_type == 'whatsapp_qr':
        try:
            from utils.wahooks_connections import delete_wahooks_connection
            connection_id = get_encryption().decrypt_credential(row.credential).get('connection_id')
            if connection_id:
                await delete_wahooks_connection(connection_id)
        except Exception as e:
            logger.error(f"[CredentialDelete] Failed to delete WAHooks connection: {e}")

    # A bought phone number goes back to the provider with its credential; the
    # recurring charge row dies with the credential.
    if credential_type == 'phone_number':
        from utils.capabilities import PHONE_NUMBERS, capability
        numbers = capability(PHONE_NUMBERS)
        if numbers is not None:
            try:
                number_sid = get_encryption().decrypt_credential(row.credential).get('number_sid')
                if number_sid:
                    await numbers.release(number_sid)
            except Exception as e:
                logger.error(f"[CredentialDelete] Failed to release phone number: {e}")

    await repo.delete_credential_and_shares(credential_id)
