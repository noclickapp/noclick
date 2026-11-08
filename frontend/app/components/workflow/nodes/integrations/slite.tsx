import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SliteIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/slite.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const SliteNode: NodeDefinition = {
    type: 'automation-slite', label: 'Slite',
    description: 'Search, create and update knowledge base notes, reviews, users and groups',
    keywords: ['wiki', 'knowledge base', 'documents'],
    Icon: SliteIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SliteIcon} iconColor="" />),
};
