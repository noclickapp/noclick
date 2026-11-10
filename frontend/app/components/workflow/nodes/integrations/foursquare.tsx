import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const FoursquareIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/foursquare.svg" dark="/icons/foursquare-dark.svg" className={className} style={style} />
);

export const FoursquareNode: NodeDefinition = {
    type: 'automation-foursquare', category: 'content-research', label: 'Foursquare',
    description: 'Search and enrich places, suggest edits, and confirm geotagging',
    Icon: FoursquareIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FoursquareIcon} iconColor="" />),
};
