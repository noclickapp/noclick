// YouTube automation node definition.
// Uses AutomationNode component with YouTube-specific configuration.
// Enables interacting with YouTube Data API via Google OAuth credentials.

import { memo, SVGProps } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 60 };

// Custom YouTube icon component that renders the multi-colored SVG
const YouTubeIcon = ({ className, style, ...props }: SVGProps<SVGSVGElement>) => (
    <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 48 48"
        className={className}
        style={style}
        {...props}
    >
        <path fill="#FF3D00" d="M43.2,33.9c-0.4,2.1-2.1,3.7-4.2,4c-3.3,0.5-8.8,1.1-15,1.1c-6.1,0-11.6-0.6-15-1.1c-2.1-0.3-3.8-1.9-4.2-4C4.4,31.6,4,28.2,4,24c0-4.2,0.4-7.6,0.8-9.9c0.4-2.1,2.1-3.7,4.2-4C12.3,9.6,17.8,9,24,9c6.2,0,11.6,0.6,15,1.1c2.1,0.3,3.8,1.9,4.2,4c0.4,2.3,0.9,5.7,0.9,9.9C44,28.2,43.6,31.6,43.2,33.9z"/>
        <path fill="#FFF" d="M20 31L20 17 32 24z"/>
    </svg>
);

const YouTubeNodeComponent = (props: NodeProps) => {
    // Pass empty iconColor since the SVG has its own colors
    return <AutomationNode {...props} Icon={YouTubeIcon as any} iconColor="" />;
};

export const YouTubeNode: NodeDefinition = {
    type: 'automation-youtube',
    label: 'YouTube',
    description: 'YouTube automation',
    Icon: YouTubeIcon as any,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(YouTubeNodeComponent),
};
