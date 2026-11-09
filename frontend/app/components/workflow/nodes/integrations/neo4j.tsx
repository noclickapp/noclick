import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Neo4jIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/neo4j.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const Neo4jNode: NodeDefinition = {
    type: 'automation-neo4j', category: 'databases-storage', label: 'Neo4j',
    description: 'Manage Neo4j Aura instances, snapshots, projects and encryption keys',
    Icon: Neo4jIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Neo4jIcon} iconColor="" />),
};
