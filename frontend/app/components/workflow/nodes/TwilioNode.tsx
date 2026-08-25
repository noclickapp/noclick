// Twilio Communications Platform automation node definition.
// Provides workflow integration with Twilio for SMS, WhatsApp, Voice, Verify, Conversations, and SendGrid Email.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Create icon component from SVG file
const TwilioIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/twilio.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
TwilioIcon.displayName = 'TwilioIcon';

const TwilioNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={TwilioIcon} iconColor="" />;
};

export const TwilioNode: NodeDefinition = {
    type: 'automation-twilio',
    label: 'Twilio',
    description: 'Twilio automation',
    Icon: TwilioIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(TwilioNodeComponent),
};
