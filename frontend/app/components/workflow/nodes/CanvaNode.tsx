// Canva Connect API automation node definition.
// Provides workflow integration with Canva for designs, assets, folders, and exports.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Create icon component from SVG file
const CanvaIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/canva.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
CanvaIcon.displayName = 'CanvaIcon';

const CanvaNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={CanvaIcon} iconColor="" />;
};

export const CanvaNode: NodeDefinition = {
    type: 'automation-canva',
    label: 'Canva',
    description: 'Canva automation',
    Icon: CanvaIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(CanvaNodeComponent),
};
