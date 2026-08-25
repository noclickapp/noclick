// Upstash Redis REST API automation node definition.
// Provides workflow integration with Redis for strings, hashes, lists, sets, sorted sets, and keys.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Create icon component from SVG file
const RedisIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/redis-logo.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
RedisIcon.displayName = 'RedisIcon';

const RedisNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={RedisIcon} iconColor="" />;
};

export const RedisNode: NodeDefinition = {
    type: 'automation-redis',
    label: 'Redis',
    description: 'Redis automation',
    Icon: RedisIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(RedisNodeComponent),
};
