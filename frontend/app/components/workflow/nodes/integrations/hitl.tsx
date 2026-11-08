import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HitlIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/hitl.png" alt="" aria-hidden="true" className={`brand-mono ${className || ''}`}
        style={{ ...style, objectFit: 'contain', filter: `invert(1) ${style?.filter || 'invert(var(--brand-invert, 0))'}` }} />
);

export const HitlNode: NodeDefinition = {
    type: 'automation-hitl', category: 'ai', label: 'Hitl',
    description: 'Route review requests to humans and manage loops, members and feedback',
    keywords: ['HITL.sh', 'human in the loop', 'approval', 'human review'],
    Icon: HitlIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HitlIcon} iconColor="" />),
};
