import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MemIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/mem.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const MemNode: NodeDefinition = {
    type: 'automation-mem', category: 'productivity', label: 'Mem',
    description: 'Create, search and organize Mem notes and collections',
    Icon: MemIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MemIcon} iconColor="" />),
};
