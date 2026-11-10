import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const SupermemoryIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/supermemory.svg" dark="/icons/supermemory-dark.svg" className={className} style={style} />
);

export const SupermemoryNode: NodeDefinition = {
    type: 'automation-supermemory', category: 'ai', label: 'Supermemory',
    description: 'Store documents, search memories, build profiles and manage namespaces and connectors',
    keywords: ['memory', 'rag', 'search', 'knowledge'],
    Icon: SupermemoryIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SupermemoryIcon} iconColor="" />),
};
