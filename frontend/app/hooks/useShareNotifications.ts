/**
 * Hook for displaying real-time share notifications.
 * Listens for share:notification events (via Event Relay) and shows toast notifications
 * when someone shares a resource with the user.
 */

import { useCallback } from 'react';
import { toast } from 'sonner';
import { useSocketEvent } from './useSocketEvent';
import type { ShareNotificationEvent } from '~/types/socket-events.generated';

/**
 * Hook that listens for share notifications and displays toasts.
 * Should be used at the dashboard layout level to receive notifications globally.
 *
 * @example
 * // In dashboard.tsx
 * useShareNotifications();
 */
export function useShareNotifications(): void {
    const handleShareNotification = useCallback((data: ShareNotificationEvent) => {
        const resourceTypeLabel = data.resource_type === 'workflow' ? 'workflow' : 'database';
        const permissionLabel = data.permission === 'edit' ? 'edit access' : 'view access';
        const sharer = data.shared_by_name || data.shared_by_email;

        toast.success(`${sharer} shared a ${resourceTypeLabel} with you`, {
            description: `"${data.resource_name}" - ${permissionLabel}`,
            duration: 6000,
        });
    }, []);

    useSocketEvent('share:notification', handleShareNotification, [handleShareNotification]);
}
