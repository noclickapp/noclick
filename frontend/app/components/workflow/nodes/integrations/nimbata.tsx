import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const NimbataIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/nimbata.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const NimbataNode: NodeDefinition = {
    type: 'automation-nimbata', category: 'marketing', label: 'Nimbata',
    description: 'Read calls and leads; manage call tags, ratings, values and follow-ups',
    keywords: ['call tracking', 'attribution', 'lead tracking'],
    Icon: NimbataIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NimbataIcon} iconColor="" />),
};
