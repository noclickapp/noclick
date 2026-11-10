import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://stackit.com/de
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/stackitdns-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const STACKITDNSNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
);
export const STACKITDNSNode: NodeDefinition = {
    type: 'automation-stackitdns', category: 'cloud-hosting', label: 'STACKIT DNS',
    description: 'Protected zone and RRset metadata without DNS record values or changes',
    keywords: ['STACKIT DNS', 'zone metadata', 'RRset status', 'DNS metadata'],
    Icon: OfficialBrandIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: STACKITDNSNodeComponent,
};
