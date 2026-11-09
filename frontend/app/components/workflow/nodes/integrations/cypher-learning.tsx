import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CypherLearningIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/cypher-learning.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const CypherLearningNode: NodeDefinition = {
    type: 'automation-cypher-learning', category: 'courses', label: 'CYPHER Learning',
    description: 'Manage learners, classes, enrollments, groups and grades',
    Icon: CypherLearningIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CypherLearningIcon} iconColor="" />),
};
