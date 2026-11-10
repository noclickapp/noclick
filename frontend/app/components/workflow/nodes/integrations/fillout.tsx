import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://www.fillout.com
import type { CSSProperties as BrandCSSProperties } from 'react';

// Fillout's own favicon PNG (its app mark exists only as raster)
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/fillout-preferred-brand.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

export const FilloutIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/fillout.svg" alt="" className={className} style={style} {...props} />
));
FilloutIcon.displayName = 'FilloutIcon';

const FilloutNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />
);

export const FilloutNode: NodeDefinition = {
    type: 'automation-fillout',
    label: 'Fillout',
    description: 'Fillout forms, submissions, and Zite databases',
    category: 'forms',
    Icon: PreferredBrandIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(FilloutNodeComponent),
};
