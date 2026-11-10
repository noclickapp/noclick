import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const Neo4jIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/neo4j.svg" dark="/icons/neo4j-dark.svg" className={className} style={style} />
);

export const Neo4jNode: NodeDefinition = {
    type: 'automation-neo4j', category: 'databases-storage', label: 'Neo4j',
    description: 'Manage Neo4j Aura instances, snapshots, projects and encryption keys',
    Icon: Neo4jIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Neo4jIcon} iconColor="" />),
};
