// Monday.com work-management automation node definition.
// Provides workflow integration with the monday.com Platform GraphQL API
// (boards, items, groups, columns, updates, notifications, users, workspaces,
// webhooks) plus a webhook trigger for board events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const MondayIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/monday.svg" alt="" className={className} style={style} {...props} />
));
MondayIcon.displayName = 'MondayIcon';

const MondayNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={MondayIcon} iconColor="" />;
};

export const MondayNode: NodeDefinition = {
    type: 'automation-monday',
    label: 'Monday.com',
    description: 'Monday.com work-management automation',
    Icon: MondayIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(MondayNodeComponent),
};
