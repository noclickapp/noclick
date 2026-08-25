// Google Meet automation node definition.
// Provides workflow integration with the Google Meet REST API (spaces,
// conference records, participants, recordings, transcripts, space members)
// via Google OAuth credentials.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const GoogleMeetIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/google-meet.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
GoogleMeetIcon.displayName = 'GoogleMeetIcon';

const GoogleMeetNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={GoogleMeetIcon} iconColor="" />;
};

export const GoogleMeetNode: NodeDefinition = {
    type: 'automation-google-meet',
    label: 'Google Meet',
    description: 'Google Meet automation',
    Icon: GoogleMeetIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoogleMeetNodeComponent),
};
