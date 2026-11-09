// Vybit Notifications exposes developer API actions in the workflow editor.
// The provider's official icon identifies the integration in the catalog and canvas.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const VybitNotificationsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/vybit-notifications.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
VybitNotificationsIcon.displayName = 'VybitNotificationsIcon';

export const VybitNotificationsNode: NodeDefinition = {
    type: 'automation-vybit-notifications',
    label: 'Vybit Notifications',
    description: 'Send sound-based push notifications and manage vybits, reminders and subscriptions.',
    category: 'communication',
    keywords: ['vybit', 'push', 'notification', 'sound', 'reminder'],
    Icon: VybitNotificationsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VybitNotificationsIcon} iconColor="" />),
};
