import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const BusinessmapIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/businessmap.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
BusinessmapIcon.displayName = 'BusinessmapIcon';

export const BusinessmapNode: NodeDefinition = {
    type: 'automation-businessmap',
    label: 'Businessmap',
    description: 'Manage cards, comments, subtasks and time; react to board events',
    category: 'productivity',
    keywords: ['kanbanize', 'kanban', 'projects', 'cards'],
    Icon: BusinessmapIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BusinessmapIcon} iconColor="" />),
};
