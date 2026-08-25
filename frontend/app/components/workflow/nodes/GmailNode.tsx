// Gmail automation node definition.
// Uses AutomationNode component with Gmail-specific configuration.
// Enables sending and reading emails via Google OAuth credentials.

import { memo, SVGProps } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 60 };

// Custom Gmail icon component that renders the multi-colored SVG
// Accepts className for sizing but ignores color classes since the SVG has its own colors
const GmailIcon = ({ className, style, ...props }: SVGProps<SVGSVGElement>) => (
    <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 48 48"
        className={className}
        style={style}
        {...props}
    >
        <path fill="#4caf50" d="M45,16.2l-5,2.75l-5,4.75L35,40h7c1.657,0,3-1.343,3-3V16.2z"/>
        <path fill="#1e88e5" d="M3,16.2l3.614,1.71L13,23.7V40H6c-1.657,0-3-1.343-3-3V16.2z"/>
        <polygon fill="#e53935" points="35,11.2 24,19.45 13,11.2 12,17 13,23.7 24,31.95 35,23.7 36,17"/>
        <path fill="#c62828" d="M3,12.298V16.2l10,7.5V11.2L9.876,8.859C9.132,8.301,8.228,8,7.298,8h0C4.924,8,3,9.924,3,12.298z"/>
        <path fill="#fbc02d" d="M45,12.298V16.2l-10,7.5V11.2l3.124-2.341C38.868,8.301,39.772,8,40.702,8h0 C43.076,8,45,9.924,45,12.298z"/>
    </svg>
);

const GmailNodeComponent = (props: NodeProps) => {
    // Pass empty iconColor since the SVG has its own colors
    return <AutomationNode {...props} Icon={GmailIcon as any} iconColor="" />;
};

export const GmailNode: NodeDefinition = {
    type: 'automation-gmail',
    label: 'Gmail',
    description: 'Send and read emails',
    Icon: GmailIcon as any,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GmailNodeComponent),
};
