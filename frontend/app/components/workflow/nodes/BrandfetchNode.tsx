// Brandfetch brand intelligence automation node definition.
// Provides workflow integration with the Brandfetch REST API (brand lookups,
// brand context, search, transaction identification, logo CDN URLs) plus a
// webhook trigger for brand-change events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const BrandfetchIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/brandfetch.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
BrandfetchIcon.displayName = 'BrandfetchIcon';

const BrandfetchNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={BrandfetchIcon} iconColor="" />;
};

export const BrandfetchNode: NodeDefinition = {
    type: 'automation-brandfetch',
    label: 'Brandfetch',
    description: 'Brandfetch brand intelligence automation',
    Icon: BrandfetchIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(BrandfetchNodeComponent),
};
