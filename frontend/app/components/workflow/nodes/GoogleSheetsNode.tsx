// Google Sheets automation node definition.
// Uses AutomationNode component with Google Sheets-specific configuration.
// Enables reading and writing data from Google Sheets via OAuth credentials.

import { memo, forwardRef, SVGProps, useId } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 60 };

// Inline SVG component for instant rendering (no network request/pop-in)
const GoogleSheetsIcon: SvgIconComponent = forwardRef<SVGSVGElement, SVGProps<SVGSVGElement>>(
    ({ className, style, ...props }, ref) => {
        const gradientId = useId();
        return (
            <svg
                ref={ref}
                viewBox="0 0 48 48"
                xmlns="http://www.w3.org/2000/svg"
                className={className}
                style={style}
                {...props}
            >
                <defs>
                    <linearGradient id={gradientId} x1="24" y1="12.8696" x2="24" y2="94.8387" gradientUnits="userSpaceOnUse">
                        <stop offset="0" stopColor="#21AD64" />
                        <stop offset="1" stopColor="#088242" />
                    </linearGradient>
                </defs>
                <path fill={`url(#${gradientId})`} d="M39,15v27c0,1.105-0.895,2-2,2H11c-1.105,0-2-0.895-2-2V6c0-1.105,0.895-2,2-2h17L39,15z" />
                <path fill="#107C42" d="M28,4v10c0,0.552,0.448,1,1,1h10L28,4z" />
                <path opacity="0.05" d="M16,33c-1.103,0-2-0.897-2-2V21c0-1.103,0.897-2,2-2h16c1.103,0,2,0.897,2,2v10c0,1.103-0.897,2-2,2H16z M30,29v-1h-4v1H30z M22,29v-1h-4v1H22z M30,24v-1h-4v1H30z M22,24v-1h-4v1H22z" />
                <path opacity="0.07" d="M16,32.5c-0.827,0-1.5-0.673-1.5-1.5V21c0-0.827,0.673-1.5,1.5-1.5h16c0.827,0,1.5,0.673,1.5,1.5v10c0,0.827-0.673,1.5-1.5,1.5H16z M30.5,29.5v-2h-5v2H30.5z M22.5,29.5v-2h-5v2H22.5z M30.5,24.5v-2h-5v2H30.5z M22.5,24.5v-2h-5v2H22.5z" />
                <path fill="#FFFFFF" d="M32,20H16c-0.553,0-1,0.448-1,1v10c0,0.552,0.447,1,1,1h16c0.553,0,1-0.448,1-1V21C33,20.448,32.553,20,32,20z M31,25h-6v-3h6V25z M23,22v3h-6v-3H23z M17,27h6v3h-6V27z M25,30v-3h6v3H25z" />
            </svg>
        );
    }
);
GoogleSheetsIcon.displayName = 'GoogleSheetsIcon';

const GoogleSheetsNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={GoogleSheetsIcon}
            iconColor=""
            width={DIMENSIONS.width}
            height={DIMENSIONS.height}
            iconSize={DIMENSIONS.iconSize}
        />
    );
};

export const GoogleSheetsNode: NodeDefinition = {
    type: 'automation-google-sheets',
    label: 'Google Sheets',
    description: 'Google Sheets data',
    Icon: GoogleSheetsIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoogleSheetsNodeComponent),
};
