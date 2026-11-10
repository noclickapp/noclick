import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://developers.genesiscloud.com/compute-api/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/genesiscloud.svg" dark="/icons/genesiscloud-dark.svg" className={className} style={style} />
);

export const GenesisCloudNode: NodeDefinition = {
    type: 'automation-genesiscloud',
    label: 'Genesis Cloud',
    category: 'cloud-hosting',
    description: 'Read existing instance inventory and selected instance metadata',
    keywords: ['genesiscloud', 'genesis cloud', 'cloud', 'instance', 'inventory', 'compute'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
