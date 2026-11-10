import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

// Original vendor wordmark; docs/engineering/bloomerang-icon-provenance.md.

import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://bloomerang.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/bloomerang-brand-vector.svg" dark="/icons/bloomerang-brand-vector-dark.svg" className={className} style={style} />
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
