// Instantly email automation node definition.
// Provides workflow integration for email outreach, campaigns, leads, and analytics.

import { memo, forwardRef, SVGProps } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 54 };

// Inline SVG component for instant rendering (no network request/pop-in)
const InstantlyIcon: SvgIconComponent = forwardRef<SVGSVGElement, SVGProps<SVGSVGElement>>(
    ({ className, style, ...props }, ref) => (
        <svg
            ref={ref}
            viewBox="0 0 32 32"
            xmlns="http://www.w3.org/2000/svg"
            className={className}
            style={style}
            {...props}
        >
            <path d="M16.0039 32C24.8405 32 32.0039 24.8366 32.0039 16C32.0039 7.16344 24.8405 0 16.0039 0C7.16735 0 0.00390625 7.16344 0.00390625 16C0.00390625 24.8366 7.16735 32 16.0039 32Z" fill="#0081FF"/>
            <path d="M11.5253 18.3125H7.27703C7.12763 18.3125 7.03373 18.151 7.10801 18.0212L13.9132 6.12891H23.8717C24.0332 6.12891 24.1246 6.3142 24.0257 6.44231L19.1602 12.753C19.0617 12.8811 19.1527 13.0664 19.3142 13.0664H24.5102C24.6855 13.0664 24.7714 13.2797 24.645 13.4011L9.8427 27.6479C9.70206 27.7832 9.47212 27.6505 9.51886 27.461L11.7144 18.5533C11.7444 18.431 11.6518 18.3125 11.5253 18.3125Z" fill="#fff"/>
        </svg>
    )
);
InstantlyIcon.displayName = 'InstantlyIcon';

const InstantlyNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={InstantlyIcon}
            iconColor=""
            width={DIMENSIONS.width}
            height={DIMENSIONS.height}
            iconSize={DIMENSIONS.iconSize}
        />
    );
};

export const InstantlyNode: NodeDefinition = {
    type: 'automation-instantly',
    label: 'Instantly',
    description: 'Email automation',
    Icon: InstantlyIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(InstantlyNodeComponent),
};
