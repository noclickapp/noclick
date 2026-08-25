// Tableau analytics & BI automation node definition.
// Provides workflow integration with the Tableau REST API (projects, workbooks,
// views, data sources, users/groups, webhooks) plus a webhook trigger for
// Tableau events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const TableauIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/tableau.svg" alt="" className={className} style={style} {...props} />
));
TableauIcon.displayName = 'TableauIcon';

const TableauNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={TableauIcon} iconColor="" />;
};

export const TableauNode: NodeDefinition = {
    type: 'automation-tableau',
    label: 'Tableau',
    description: 'Tableau analytics & BI automation',
    Icon: TableauIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(TableauNodeComponent),
};
