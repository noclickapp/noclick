// RocketReach's self-registering canvas and catalog definition.
// The provider mark is served locally with its provenance beside the asset.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const RocketReachIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/rocket-reach.svg" className={className} style={style} />
);

export const RocketReachNode: NodeDefinition = {
    type: 'automation-rocket-reach', category: 'crm-sales', label: 'RocketReach',
    keywords: ['Rocket Reach', 'prospecting', 'enrichment', 'email finder'],
    description: 'Find and enrich people and companies, verify emails, and monitor updated contacts',
    Icon: RocketReachIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RocketReachIcon} iconColor="" />),
};
