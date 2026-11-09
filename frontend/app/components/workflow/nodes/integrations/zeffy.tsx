import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ZeffyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/zeffy.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ZeffyNode: NodeDefinition = {
    type: 'automation-zeffy', category: 'nonprofit', label: 'Zeffy',
    description: 'Manage nonprofit contacts and offline payments; read campaigns and team members',
    Icon: ZeffyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZeffyIcon} iconColor="" />),
};
