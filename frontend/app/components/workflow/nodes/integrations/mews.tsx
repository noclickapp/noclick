import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const MewsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/mews.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
MewsIcon.displayName = 'MewsIcon';

export const MewsNode: NodeDefinition = {
    type: 'automation-mews',
    label: 'Mews',
    description: 'Manage hotel guests, reservations, rooms and tasks',
    category: 'industry',
    keywords: ['hotel', 'hospitality', 'property management', 'PMS', 'check in', 'check out', 'housekeeping'],
    Icon: MewsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MewsIcon} iconColor="" />),
};
