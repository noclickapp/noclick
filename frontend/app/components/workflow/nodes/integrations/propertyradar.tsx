import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PropertyRadarIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/propertyradar.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const PropertyRadarNode: NodeDefinition = {
    type: 'automation-propertyradar', category: 'industry', label: 'PropertyRadar',
    description: 'Search properties and manage real estate lists, members and webhooks',
    Icon: PropertyRadarIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PropertyRadarIcon} iconColor="" />),
};
