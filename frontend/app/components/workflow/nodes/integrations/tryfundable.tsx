// Defines Tryfundable in the workflow palette and integration catalog.
// Uses the official Fundable mark so sourcing and enrichment workflows are easy to find.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const TryfundableIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/tryfundable.svg" dark="/icons/tryfundable-dark.svg" className={className} style={style} />
);

export const TryfundableNode: NodeDefinition = {
    type: 'automation-tryfundable', category: 'crm-sales', label: 'Tryfundable',
    description: 'Discover companies, funding rounds, investors and people; enrich contacts and read saved alerts',
    keywords: ['Fundable', 'startup', 'venture capital', 'funding', 'investor', 'enrichment'],
    Icon: TryfundableIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TryfundableIcon} iconColor="" />),
};
