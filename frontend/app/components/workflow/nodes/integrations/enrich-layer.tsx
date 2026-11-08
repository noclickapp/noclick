import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const EnrichLayerIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/enrich-layer.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const EnrichLayerNode: NodeDefinition = {
    type: 'automation-enrich-layer', category: 'crm-sales', label: 'Enrich Layer',
    description: 'Enrich people and companies, find contacts and search jobs',
    Icon: EnrichLayerIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EnrichLayerIcon} iconColor="" />),
};
