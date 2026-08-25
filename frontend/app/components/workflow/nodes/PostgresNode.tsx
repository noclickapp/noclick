// PostgreSQL database automation node definition.
// Provides workflow integration with PostgreSQL for queries, inserts, updates, and schema introspection.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Create icon component from SVG file
const PostgresIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/postgres.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
PostgresIcon.displayName = 'PostgresIcon';

const PostgresNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={PostgresIcon} iconColor="" />;
};

export const PostgresNode: NodeDefinition = {
    type: 'automation-postgres',
    label: 'PostgreSQL',
    description: 'PostgreSQL automation',
    Icon: PostgresIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(PostgresNodeComponent),
};
