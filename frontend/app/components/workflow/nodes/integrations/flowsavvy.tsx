// FlowSavvy's catalog and canvas definition use the official provider icon.
// Backend-generated schemas supply the operation and credential forms.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FlowSavvyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/flowsavvy.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const FlowSavvyNode: NodeDefinition = {
    type: 'automation-flowsavvy', category: 'productivity', label: 'FlowSavvy',
    description: 'Automate tasks, events and schedules, and watch for new or updated items',
    keywords: ['tasks', 'calendar', 'time blocking', 'scheduling'],
    Icon: FlowSavvyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FlowSavvyIcon} iconColor="" />),
};
