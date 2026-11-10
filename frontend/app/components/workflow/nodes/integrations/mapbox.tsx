import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const MapboxIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/mapbox.svg" dark="/icons/mapbox-dark.svg" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const MapboxNode: NodeDefinition = {
    type: 'automation-mapbox', category: 'developer-tools', label: 'Mapbox',
    description: 'Geocode addresses and manage Mapbox styles, drafts and sprites',
    Icon: MapboxIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MapboxIcon} iconColor="" />),
};
