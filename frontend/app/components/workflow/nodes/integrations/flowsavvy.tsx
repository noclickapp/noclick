// FlowSavvy's catalog and canvas definition use the official provider icon.
// Backend-generated schemas supply the operation and credential forms.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const FlowSavvyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/flowsavvy.svg" className={className} style={style} />
);

export const FlowSavvyNode: NodeDefinition = {
    type: 'automation-flowsavvy', category: 'productivity', label: 'FlowSavvy',
    description: 'Automate tasks, events and schedules, and watch for new or updated items',
    keywords: ['tasks', 'calendar', 'time blocking', 'scheduling'],
    Icon: FlowSavvyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FlowSavvyIcon} iconColor="" />),
};
