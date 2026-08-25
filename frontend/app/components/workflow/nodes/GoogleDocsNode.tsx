// Google Docs automation node definition.
// Uses AutomationNode component with Google Docs-specific configuration.
// Enables creating, reading, and editing documents via OAuth credentials.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 46 };

// Create icon component from SVG file
const GoogleDocsIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/google-docs.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
GoogleDocsIcon.displayName = 'GoogleDocsIcon';

const GoogleDocsNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={GoogleDocsIcon} iconColor="" />;
};

export const GoogleDocsNode: NodeDefinition = {
    type: 'automation-google-docs',
    label: 'Google Docs',
    description: 'Document automation',
    Icon: GoogleDocsIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoogleDocsNodeComponent),
};
