// Google Business Profile (GBP) automation node definition.
// Uses AutomationNode component with GBP-specific configuration.
// Enables pulling location data, performance metrics, and reviews via OAuth credentials.

import { memo, forwardRef, SVGProps } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 60 };

// Official Google My Business / Google Business Profile icon (storefront with Google G)
const GoogleBusinessProfileIcon: SvgIconComponent = forwardRef<SVGSVGElement, SVGProps<SVGSVGElement>>(
    ({ className, style, ...props }, ref) => {
        return (
            <svg
                ref={ref}
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 122.88 107.25"
                className={className}
                style={style}
                {...props}
            >
                {/* Main storefront body */}
                <path fill="#4989F5" d="M10.43,26.86h99c2.35,0,4.26,1.91,4.26,4.26v71.88c0,2.35-1.91,4.26-4.26,4.26h-99c-2.35,0-4.26-1.91-4.26-4.26V31.12C6.17,28.76,8.08,26.86,10.43,26.86z" />
                {/* Roof triangles */}
                <polygon fill="#3C4BA6" points="30.72,40.32 61.44,40.32 61.44,0 35.32,0" />
                <path fill="#7BABF7" d="M92.16,40.32H61.44V0h26.12L92.16,40.32z" />
                <path fill="#3F51B5" d="M113.73,7.78l-0.04-0.14C112.72,3.18,108.77,0,104.21,0H87.56l4.6,40.32h30.72L113.73,7.78z" />
                <path fill="#7BABF7" d="M9.15,7.78l0.04-0.14C10.17,3.18,14.11,0,18.68,0h16.64l-4.6,40.32H0L9.15,7.78z" />
                {/* Storefront awning half-circles */}
                <path fill="#709BE0" fillRule="evenodd" clipRule="evenodd" d="M30.78,40.31c0,8.48-6.87,15.35-15.35,15.35c-8.48,0-15.35-6.87-15.35-15.35H30.78z" />
                <path fill="#3C4BA6" fillRule="evenodd" clipRule="evenodd" d="M61.48,40.31c0,8.48-6.87,15.35-15.35,15.35c-8.48,0-15.35-6.87-15.35-15.35H61.48z" />
                <path fill="#709BE0" fillRule="evenodd" clipRule="evenodd" d="M92.18,40.31c0,8.48-6.87,15.35-15.35,15.35c-8.48,0-15.35-6.87-15.35-15.35H92.18z" />
                <path fill="#3C4BA6" fillRule="evenodd" clipRule="evenodd" d="M122.88,40.31c0,8.48-6.87,15.35-15.35,15.35c-8.48,0-15.35-6.87-15.35-15.35H122.88z" />
                {/* Google G logo */}
                <path fill="#FFFFFF" d="M107.53,81.9c-0.05-0.73-0.14-1.4-0.27-2.25H90.51c0,2.34,0,4.9-0.01,7.24h9.7c-0.42,2.21-1.7,4.16-3.55,5.42c-1.86,1.26,0-0.04-0.01-0.04c-1.19,0.78-2.53,1.3-3.93,1.53c-0.68,0.12-1.38,0.19-2.08,0.19c-0.73,0-1.46-0.07-2.17-0.21c-1.42-0.29-2.77-0.88-3.96-1.72c-1.75-1.24-3.11-2.98-3.89-4.98c-0.06-0.16-0.12-0.31-0.17-0.47v-0.02l0.02-0.01c-0.38-1.11-0.57-2.29-0.57-3.46c0-1.17,0.19-2.34,0.57-3.45c0.53-1.57,1.42-3.01,2.58-4.19c2.72-2.82,6.79-3.88,10.55-2.75c1.44,0.44,2.75,1.22,3.84,2.26l3.27-3.27c0.58-0.58,1.18-1.15,1.73-1.75c-1.66-1.55-3.61-2.76-5.73-3.55c-1.97-0.71-4.05-1.08-6.14-1.08c-1.99,0-3.97,0.33-5.85,0.97c-0.14,0.05-0.27,0.09-0.4,0.14c-4.2,1.58-7.65,4.68-9.68,8.68c-0.71,1.41-1.24,2.92-1.55,4.48c-1.85,9.21,3.77,18.28,12.84,20.72c2.97,0.79,6.12,0.77,9.11,0.1c2.71-0.61,5.23-1.92,7.29-3.79c2.15-1.98,3.7-4.62,4.5-7.42c0.52-1.84,0.79-3.75,0.79-5.66C107.6,83.01,107.57,82.45,107.53,81.9z" />
            </svg>
        );
    }
);
GoogleBusinessProfileIcon.displayName = 'GoogleBusinessProfileIcon';

const GoogleBusinessProfileNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={GoogleBusinessProfileIcon}
            iconColor=""
            width={DIMENSIONS.width}
            height={DIMENSIONS.height}
            iconSize={DIMENSIONS.iconSize}
        />
    );
};

export const GoogleBusinessProfileNode: NodeDefinition = {
    type: 'automation-google-business-profile',
    label: 'Google Business Profile',
    description: 'GBP locations & reviews',
    Icon: GoogleBusinessProfileIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoogleBusinessProfileNodeComponent),
};
