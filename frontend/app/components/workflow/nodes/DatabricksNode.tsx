// Databricks workspace automation node definition.
// Provides workflow integration with the Databricks REST API (SQL, jobs,
// clusters, Unity Catalog, workspace, secrets) plus a webhook receiver trigger.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const DatabricksIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/databricks.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
DatabricksIcon.displayName = 'DatabricksIcon';

const DatabricksNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={DatabricksIcon} iconColor="" />;
};

export const DatabricksNode: NodeDefinition = {
    type: 'automation-databricks',
    label: 'Databricks',
    description: 'Databricks workspace automation',
    Icon: DatabricksIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(DatabricksNodeComponent),
};
