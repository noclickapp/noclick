// Hacker News automation node definition.
// Provides workflow integration with the official Hacker News API for fetching stories, comments, and users.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Create icon component from SVG file
const HackerNewsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/hackernews.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
HackerNewsIcon.displayName = 'HackerNewsIcon';

const HackerNewsNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={HackerNewsIcon} iconColor="" />;
};

export const HackerNewsNode: NodeDefinition = {
    type: 'automation-hackernews',
    label: 'Hacker News',
    description: 'News automation',
    Icon: HackerNewsIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(HackerNewsNodeComponent),
};
