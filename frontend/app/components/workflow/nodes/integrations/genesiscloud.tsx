import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://developers.genesiscloud.com/compute-api/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <>
        <img src="/icons/genesiscloud.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
        <img src="/icons/genesiscloud-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
    </>
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
