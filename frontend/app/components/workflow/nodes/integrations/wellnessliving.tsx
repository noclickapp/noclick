// WellnessLiving's self-registering definition makes client and booking operations
// available in the canvas and integration catalog. Schemas come from the backend.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WellnessLivingIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/wellnessliving.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const WellnessLivingNode: NodeDefinition = {
    type: 'automation-wellnessliving', category: 'bookings', label: 'WellnessLiving',
    description: 'Manage clients, groups, attendance, bookings, purchase options and subscriptions',
    keywords: ['fitness', 'studio', 'gym', 'wellness', 'memberships', 'scheduling'],
    Icon: WellnessLivingIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WellnessLivingIcon} iconColor="" />),
};
