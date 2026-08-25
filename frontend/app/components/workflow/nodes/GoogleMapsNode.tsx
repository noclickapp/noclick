// Google Maps Platform automation node definition.
// Provides workflow integration with the Google Maps Platform REST APIs
// (geocoding, places, routes, address validation, time zone, elevation, roads).

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const GoogleMapsIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/google-maps.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
GoogleMapsIcon.displayName = 'GoogleMapsIcon';

const GoogleMapsNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={GoogleMapsIcon} iconColor="" />;
};

export const GoogleMapsNode: NodeDefinition = {
    type: 'automation-google-maps',
    label: 'Google Maps',
    description: 'Google Maps Platform automation',
    Icon: GoogleMapsIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoogleMapsNodeComponent),
};
