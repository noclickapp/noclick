// HubSpot CRM automation node definition.
// Provides workflow integration with HubSpot CRM for contacts, companies, deals, and tickets.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Create icon component from SVG file
const HubSpotIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/hubspot.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
HubSpotIcon.displayName = 'HubSpotIcon';

const HubSpotNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={HubSpotIcon} iconColor="" />;
};

export const HubSpotNode: NodeDefinition = {
    type: 'automation-hubspot',
    label: 'HubSpot',
    description: 'HubSpot automation',
    Icon: HubSpotIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(HubSpotNodeComponent),
};
