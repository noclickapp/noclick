import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const EvolutionGoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/evolution-go.svg" alt="" aria-hidden="true" className={className} style={style} />
);

export const EvolutionGoNode: NodeDefinition = {
    type: 'automation-evolution-go',
    category: 'communication',
    label: 'Evolution Go',
    description: 'Send WhatsApp messages, manage contacts and groups, and receive messages and calls',
    Icon: EvolutionGoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EvolutionGoIcon} iconColor="" />),
};
