import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const ID4iIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/id4i.svg" dark="/icons/id4i-dark.svg" className={className} style={style} />
);

export const ID4iNode: NodeDefinition = {
    type: 'automation-id4i', category: 'industry', label: 'ID4i',
    description: 'Track GUIDs, collections, properties, aliases and asset history',
    keywords: ['ID4i', 'asset tracking', 'GUID', 'traceability', 'manufacturing'],
    Icon: ID4iIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ID4iIcon} iconColor="" />),
};
