// Snowflake data-cloud automation node definition.
// Provides workflow integration with the Snowflake REST API v2 (SQL statements,
// databases, schemas/tables, warehouses, tasks, users/roles, stages).

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const SnowflakeIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/snowflake.svg" alt="" className={className} style={style} {...props} />
));
SnowflakeIcon.displayName = 'SnowflakeIcon';

const SnowflakeNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SnowflakeIcon} iconColor="" />;
};

export const SnowflakeNode: NodeDefinition = {
    type: 'automation-snowflake',
    label: 'Snowflake',
    description: 'Snowflake data-cloud automation',
    Icon: SnowflakeIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(SnowflakeNodeComponent),
};
