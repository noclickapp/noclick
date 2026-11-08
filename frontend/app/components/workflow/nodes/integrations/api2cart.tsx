import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Unmodified compact brand asset from https://api2cart.com
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/api2cart-brand.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const API2CartNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const API2CartNode: NodeDefinition = {
    type: 'automation-api2cart', category: 'ecommerce', label: 'API2Cart',
    description: 'Connected-store catalog, customer and order metadata with disposable catalog management',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 110, height: 90, iconSize: 72 },
    component: API2CartNodeComponent,
};
