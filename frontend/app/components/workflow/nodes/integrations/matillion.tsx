import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const MatillionIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/matillion.svg" dark="/icons/matillion-dark.svg" className={className} style={style} />
);
const MatillionNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={MatillionIcon} iconColor="" />;

export const MatillionNode: NodeDefinition = {
    type: 'automation-matillion', category: 'analytics-bi', label: 'Maia (Matillion)',
    description: 'Read scoped pipeline metadata and manage confirmed execution lifecycle',
    Icon: MatillionIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: MatillionNodeComponent,
};
