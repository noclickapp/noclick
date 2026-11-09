import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LeadsforgeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/leadsforge.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const LeadsforgeNode: NodeDefinition = {
    type: 'automation-leadsforge', category: 'crm-sales', label: 'Leadsforge',
    description: 'Find and enrich prospects, discover companies and track search jobs',
    Icon: LeadsforgeIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LeadsforgeIcon} iconColor="" />),
};
