// Sequenzy actions use the shared automation canvas and generated Python schema.
// The official publisher icon identifies subscriber and email automation tools.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const SequenzyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/sequenzy.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
SequenzyIcon.displayName = 'SequenzyIcon';

export const SequenzyNode: NodeDefinition = {
    type: 'automation-sequenzy',
    label: 'Sequenzy',
    description: 'Manage subscribers, tags, lists, events and sequence enrollments',
    category: 'marketing',
    keywords: ['email', 'marketing', 'subscribers', 'sequences', 'audience'],
    Icon: SequenzyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SequenzyIcon} iconColor="" />),
};
