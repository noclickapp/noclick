// Google BigQuery automation node definition.
// Provides workflow integration with the BigQuery v2 REST API (queries, jobs,
// datasets, tables, routines, models) via Google OAuth credentials.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const BigQueryIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/bigquery.svg" alt="" className={className} style={style} {...props} />
));
BigQueryIcon.displayName = 'BigQueryIcon';

const BigQueryNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={BigQueryIcon} iconColor="" />;
};

export const BigQueryNode: NodeDefinition = {
    type: 'automation-bigquery',
    label: 'Google BigQuery',
    description: 'Google BigQuery data warehouse automation',
    Icon: BigQueryIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(BigQueryNodeComponent),
};
