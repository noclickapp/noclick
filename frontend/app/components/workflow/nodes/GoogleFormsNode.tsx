// Google Forms automation node definition.
// Uses AutomationNode component with Google Forms-specific configuration.
// Enables creating forms and retrieving responses via OAuth credentials.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 46 };

// Create icon component from SVG file
const GoogleFormsIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/google-forms.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
GoogleFormsIcon.displayName = 'GoogleFormsIcon';

const GoogleFormsNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={GoogleFormsIcon} iconColor="" />;
};

export const GoogleFormsNode: NodeDefinition = {
    type: 'automation-google-forms',
    label: 'Google Forms',
    description: 'Form automation',
    Icon: GoogleFormsIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoogleFormsNodeComponent),
};
