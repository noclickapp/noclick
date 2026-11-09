// Mem0's discovered canvas definition exposes the Platform memory integration.
// Its schema and credential metadata are generated from the backend node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Mem0Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/mem0.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const Mem0Node: NodeDefinition = {
    type: 'automation-mem0', category: 'ai', label: 'Mem0',
    description: 'Store, search and manage AI memories, entities and feedback',
    keywords: ['memory', 'agents', 'personalization', 'mem0ai'],
    Icon: Mem0Icon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Mem0Icon} iconColor="" />),
};
