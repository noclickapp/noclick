import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://omnisend.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/omnisend.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const OmnisendNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
);

export const OmnisendNode: NodeDefinition = {
    type: 'automation-omnisend',
    label: 'Omnisend',
    description: 'Contacts, campaigns, automations, products, and analytics',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(OmnisendNodeComponent),
};
