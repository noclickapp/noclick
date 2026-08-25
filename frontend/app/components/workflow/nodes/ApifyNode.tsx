// Apify REST API automation node definition.
// Provides workflow integration with Apify for web scraping, actors, tasks, datasets, and more.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Create icon component from SVG file
const ApifyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/apify.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
ApifyIcon.displayName = 'ApifyIcon';

const ApifyNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ApifyIcon} iconColor="" />;
};

export const ApifyNode: NodeDefinition = {
    type: 'automation-apify',
    label: 'Apify',
    description: 'Apify automation',
    Icon: ApifyIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ApifyNodeComponent),
};
