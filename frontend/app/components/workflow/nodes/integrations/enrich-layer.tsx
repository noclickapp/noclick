import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const EnrichLayerIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/enrich-layer.svg" dark="/icons/enrich-layer-dark.svg" className={className} style={style} />
);

export const EnrichLayerNode: NodeDefinition = {
    type: 'automation-enrich-layer', category: 'crm-sales', label: 'Enrich Layer',
    description: 'Enrich people and companies, find contacts and search jobs',
    Icon: EnrichLayerIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EnrichLayerIcon} iconColor="" />),
};
