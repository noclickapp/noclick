import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PolygonIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/polygon.jpg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const PolygonNode: NodeDefinition = {
    type: 'automation-polygon', category: 'finance-accounting', label: 'Polygon',
    description: 'Read stock and forex trades, quotes, aggregates and market reference data',
    Icon: PolygonIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PolygonIcon} iconColor="" />),
};
