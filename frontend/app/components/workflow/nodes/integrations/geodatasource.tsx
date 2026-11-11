// Exposes the GeoDataSource lookup integration in the canvas and catalog.
// The SVG pair uses the provider's official mask icon; provenance records the theme fill edit.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const GeoDataSourceIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/geodatasource.svg" dark="/icons/geodatasource-dark.svg" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const GeoDataSourceNode: NodeDefinition = {
    type: 'automation-geodatasource',
    label: 'GeoDataSource Location Search',
    category: 'content-research',
    description: 'Find the nearest city, nearby cities and neighboring countries',
    keywords: ['geocoding', 'reverse geocoding', 'latitude', 'longitude', 'location', 'GeoDataSource'],
    Icon: GeoDataSourceIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GeoDataSourceIcon} iconColor="" />),
};
