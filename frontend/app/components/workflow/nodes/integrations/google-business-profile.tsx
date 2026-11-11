// Google Business Profile (GBP) automation node definition.
// Uses AutomationNode component with GBP-specific configuration.
// Enables pulling location data, performance metrics, and reviews via OAuth credentials.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 60 };

// Official Google My Business / Google Business Profile icon (storefront with Google G)
const GoogleBusinessProfileIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/google-business-profile.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

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
