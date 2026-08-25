// Google Analytics 4 (GA4) automation node definition.
// Uses AutomationNode component with GA4-specific configuration.
// Enables pulling GA4 analytics data via OAuth credentials.

import { memo, forwardRef, SVGProps } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 60 };

// Official Google Analytics icon (orange/yellow bar chart)
const GoogleAnalyticsIcon: SvgIconComponent = forwardRef<SVGSVGElement, SVGProps<SVGSVGElement>>(
    ({ className, style, ...props }, ref) => {
        return (
            <svg
                ref={ref}
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 64 64"
                className={className}
                style={style}
                {...props}
            >
                <g transform="matrix(.363638 0 0 .363636 -3.272763 -2.909091)">
                    <path d="M130 29v132c0 14.77 10.2 23 21 23 10 0 21-7 21-23V30c0-13.54-10-22-21-22s-21 9.33-21 21z" fill="#f9ab00" />
                    <path d="M75 96v65c0 14.77 10.2 23 21 23 10 0 21-7 21-23V97c0-13.54-10-22-21-22s-21 9.33-21 21z" fill="#e37400" />
                    <circle cx="41" cy="163" r="21" fill="#e37400" />
                </g>
            </svg>
        );
    }
);
GoogleAnalyticsIcon.displayName = 'GoogleAnalyticsIcon';

const GoogleAnalyticsNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={GoogleAnalyticsIcon}
            iconColor=""
            width={DIMENSIONS.width}
            height={DIMENSIONS.height}
            iconSize={DIMENSIONS.iconSize}
        />
    );
};

export const GoogleAnalyticsNode: NodeDefinition = {
    type: 'automation-google-analytics',
    label: 'Google Analytics',
    description: 'GA4 analytics data',
    Icon: GoogleAnalyticsIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoogleAnalyticsNodeComponent),
};
