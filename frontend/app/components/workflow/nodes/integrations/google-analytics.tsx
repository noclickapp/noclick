// Google Analytics 4 (GA4) automation node definition.
// Uses AutomationNode component with GA4-specific configuration.
// Enables pulling GA4 analytics data via OAuth credentials.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 60 };

// Official Google Analytics icon (orange/yellow bar chart)
const GoogleAnalyticsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/google-analytics.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

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
