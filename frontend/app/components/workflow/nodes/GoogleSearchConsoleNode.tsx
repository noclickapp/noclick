// Google Search Console automation node definition.
// Uses AutomationNode component with Search Console-specific configuration.
// Enables querying search performance data and managing sitemaps via OAuth credentials.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 46 };

const GoogleSearchConsoleIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/google-search-console.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
GoogleSearchConsoleIcon.displayName = 'GoogleSearchConsoleIcon';

const GoogleSearchConsoleNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={GoogleSearchConsoleIcon} iconColor="" />;
};

export const GoogleSearchConsoleNode: NodeDefinition = {
    type: 'automation-google-search-console',
    label: 'Google Search Console',
    description: 'Search performance & indexing',
    Icon: GoogleSearchConsoleIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoogleSearchConsoleNodeComponent),
};
