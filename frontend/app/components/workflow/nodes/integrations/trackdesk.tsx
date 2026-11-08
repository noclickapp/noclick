// Trackdesk's catalog entry and canvas node share the official provider mark.
// API schemas and credential metadata are generated from the backend node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TrackdeskIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/trackdesk.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TrackdeskNode: NodeDefinition = {
    type: 'automation-trackdesk', label: 'Trackdesk',
    description: 'Manage affiliates, offers, coupons, conversions, notes, tags and tiers',
    keywords: ['affiliate marketing', 'referrals', 'commissions', 'tracking links'],
    Icon: TrackdeskIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TrackdeskIcon} iconColor="" />),
};
