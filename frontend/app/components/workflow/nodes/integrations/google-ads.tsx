// Google Ads automation node definition.
// Uses AutomationNode component with Google Ads-specific configuration.
// Enables pulling campaign and ad performance data via OAuth credentials.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 60 };

// Official Google Ads icon (blue/yellow/green triangle)
const GoogleAdsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/google-ads.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const GoogleAdsNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={GoogleAdsIcon}
            iconColor=""
            width={DIMENSIONS.width}
            height={DIMENSIONS.height}
            iconSize={DIMENSIONS.iconSize}
        />
    );
};

export const GoogleAdsNode: NodeDefinition = {
    type: 'automation-google-ads',
    label: 'Google Ads',
    description: 'Ads performance',
    Icon: GoogleAdsIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoogleAdsNodeComponent),
};
