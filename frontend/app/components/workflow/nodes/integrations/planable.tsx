// Registers Planable in the workflow canvas and integration catalog.
// Its provider icon and social media category make the new node discoverable.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PlanableIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/planable.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const PlanableNode: NodeDefinition = {
    type: 'automation-planable', category: 'social-media', label: 'Planable',
    description: 'Manage social posts, approvals, comments, campaigns and media',
    Icon: PlanableIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PlanableIcon} iconColor="" />),
};
