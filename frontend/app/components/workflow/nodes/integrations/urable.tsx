import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const UrableIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/urable.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const UrableNode: NodeDefinition = {
    type: 'automation-urable', category: 'industry', label: 'Urable',
    description: 'Manage customers, items, jobs and calendar events; read orders, payments and proposals',
    Icon: UrableIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={UrableIcon} iconColor="" />),
};
