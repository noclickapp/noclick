// Trello project-management automation node definition.
// Provides workflow integration with the Trello REST API (boards, lists, cards,
// checklists, members, labels) plus a webhook trigger for model changes.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const TrelloIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/trello.svg" alt="" className={className} style={style} {...props} />
));
TrelloIcon.displayName = 'TrelloIcon';

const TrelloNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={TrelloIcon} iconColor="" />;
};

export const TrelloNode: NodeDefinition = {
    type: 'automation-trello',
    label: 'Trello',
    description: 'Trello project-management automation',
    Icon: TrelloIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(TrelloNodeComponent),
};
