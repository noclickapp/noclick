import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const BolnaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/bolna.svg" dark="/icons/bolna-dark.svg" className={className} style={style} />
);
export const BolnaNode: NodeDefinition = {
    type: 'automation-bolna', category: 'ai', label: 'Bolna',
    description: 'Manage voice agents, place calls, and read executions, batches and knowledge bases',
    Icon: BolnaIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BolnaIcon} iconColor="" />),
};
