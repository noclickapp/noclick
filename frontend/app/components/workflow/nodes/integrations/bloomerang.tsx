import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

// Original vendor wordmark; docs/engineering/bloomerang-icon-provenance.md.

import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://bloomerang.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/bloomerang-brand-vector.svg" alt="" aria-hidden="true" className={(className || '') + ' [--brand-invert:0] dark:[--brand-invert:1]'}
        style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
);

const BloomerangIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/bloomerang.svg" alt="" className={className} style={{ objectFit: 'contain', ...style }} {...props} />,
);
BloomerangIcon.displayName = 'BloomerangIcon';
const BloomerangNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;

export const BloomerangNode: NodeDefinition = {
    type: 'automation-bloomerang',
    label: 'Bloomerang',
    description: 'Constituents, households, interaction records and plain notes',
    category: 'nonprofit',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: BloomerangNodeComponent,
};
