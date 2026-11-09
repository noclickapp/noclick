import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MapboxIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/mapbox.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const MapboxNode: NodeDefinition = {
    type: 'automation-mapbox', category: 'developer-tools', label: 'Mapbox',
    description: 'Geocode addresses and manage Mapbox styles, drafts and sprites',
    Icon: MapboxIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MapboxIcon} iconColor="" />),
};
