// Rules every credential surface shares: how a revocation reads, and how
// someone a credential was shared with drops it from their own list.
import { sendEventAsync } from '~/lib/socket-sender';
import { ShareLeaveRequest } from '~/types/socket-events.generated';
import { invalidateCredentialsCache } from '~/utils/credentialAutoSelect';

/** "F29_user_revoked" → "disconnected"; other auto-revoke codes keep their
 *  prose with the incident prefix stripped. */
export function revokedReasonLabel(reason?: string | null): string | null {
    if (!reason) return null;
    const cleaned = reason.replace(/^F\d+_/, '').replace(/_/g, ' ');
    return cleaned === 'user revoked' ? 'disconnected' : cleaned;
}

/** Leave a credential someone shared with you. share:leave, not share:delete:
 *  dropping your OWN access needs no manage-shares permission, which a share
 *  recipient never has. Throws with a message fit to show. */
export async function leaveSharedCredential(credentialId: string): Promise<void> {
    const response = await sendEventAsync(ShareLeaveRequest.create({ resource_type: 'credential', resource_id: credentialId }));
    if (response?.error) throw new Error(response.error);
    if (!response?.removed) throw new Error('Access comes from an organization share — ask the owner to remove it.');
    invalidateCredentialsCache();
}
