// Google Contacts automation node definition.
// Uses AutomationNode component with Google Contacts-specific configuration.
// Enables managing contacts and contact groups via OAuth credentials.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 46 };

// Create icon component from SVG file
const GoogleContactsIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/google-contacts.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
GoogleContactsIcon.displayName = 'GoogleContactsIcon';

const GoogleContactsNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={GoogleContactsIcon} iconColor="" />;
};

export const GoogleContactsNode: NodeDefinition = {
    type: 'automation-google-contacts',
    label: 'Google Contacts',
    description: 'Contact management',
    Icon: GoogleContactsIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoogleContactsNodeComponent),
};
