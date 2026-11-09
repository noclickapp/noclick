// Defines the Mobile Text Alerts canvas node and integration catalog entry.
// Its generated backend schema supplies operations and manual API-key fields.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MobileTextAlertsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/mobile-text-alerts.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const MobileTextAlertsNode: NodeDefinition = {
    type: 'automation-mobile-text-alerts', category: 'communication', label: 'Mobile Text Alerts',
    description: 'Send and schedule messages, manage subscribers, groups, templates and unsubscribes',
    keywords: ['sms', 'mms', 'text messaging', 'mobile text alerts'],
    Icon: MobileTextAlertsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MobileTextAlertsIcon} iconColor="" />),
};
