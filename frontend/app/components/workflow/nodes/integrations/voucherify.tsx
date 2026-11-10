// Voucherify canvas and catalog definition. Discovered through the integration directory.
import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://voucherify.io
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/voucherify-brand-vector.svg" dark="/icons/voucherify-brand-vector-dark.svg" className={className} style={style} />
);

const VoucherifyNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
);

export const VoucherifyNode: NodeDefinition = {
    type: 'automation-voucherify',
    label: 'Voucherify',
    description: 'Customer, catalog and campaign metadata, with discount validation',
    category: 'marketing',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(VoucherifyNodeComponent),
};
