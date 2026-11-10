import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://parcellab.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <>
        <img src="/icons/parcellab-brand-vector.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
        <img src="/icons/parcellab-brand-vector-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
    </>
);

export const ParcelLabNode: NodeDefinition = {
    type: 'automation-parcellab',
    label: 'parcelLab',
    description: 'Order delivery, returns, pickup locations, promises and survey workflows',
    category: 'ecommerce',
    keywords: ['parcelLab', 'parcel', 'shipping', 'tracking', 'returns', 'PUDO', 'delivery'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
