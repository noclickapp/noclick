import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LeadboxerIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/leadboxer.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const LeadboxerNode: NodeDefinition = {
    type: 'automation-leadboxer', category: 'crm-sales', label: 'Leadboxer',
    description: 'Find and enrich leads, manage segments, tags, assignments and exclusions',
    Icon: LeadboxerIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LeadboxerIcon} iconColor="" />),
};
