// Native Bókun operations share the existing automation form and canvas behavior.
// The complete official 2026 compact mark retains its native PDF vector geometry.
import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://www.bokun.io/
import type { CSSProperties as BrandCSSProperties } from 'react';
// Native source artwork: https://www.bokun.io/wp-content/uploads/2026/02/Brand-Marketing-PDF-New-Brand.pdf
const NativeSourceBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/bokun-native-brand-20261012.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const BokunNode: NodeDefinition = {
    type: 'automation-bokun',
    label: 'Bókun',
    description: 'Read experiences, availability and booking status; manage ordinary product metadata',
    category: 'bookings',
    keywords: ['Bokun', 'tour operator', 'experiences', 'product list', 'activity availability', 'booking status'],
    Icon: NativeSourceBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NativeSourceBrandIcon} iconColor="" />),
};
