// Google Slides automation node definition.
// Uses AutomationNode component with Google Slides-specific configuration.
// Enables creating and managing presentations via OAuth credentials.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 46 };

// Create icon component from SVG file
const GoogleSlidesIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/google-slides.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
GoogleSlidesIcon.displayName = 'GoogleSlidesIcon';

const GoogleSlidesNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={GoogleSlidesIcon} iconColor="" />;
};

export const GoogleSlidesNode: NodeDefinition = {
    type: 'automation-google-slides',
    label: 'Google Slides',
    description: 'Presentation automation',
    Icon: GoogleSlidesIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoogleSlidesNodeComponent),
};
