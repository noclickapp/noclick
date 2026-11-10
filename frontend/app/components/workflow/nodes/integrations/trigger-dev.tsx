import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const TriggerDevIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/trigger-dev.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
TriggerDevIcon.displayName = 'TriggerDevIcon';

export const TriggerDevNode: NodeDefinition = {
    type: 'automation-trigger-dev',
    label: 'Trigger.dev',
    description: 'Trigger background tasks and manage runs, batches, schedules and queues',
    category: 'developer-tools',
    keywords: ['Trigger Dev', 'background jobs', 'tasks', 'schedules'],
    Icon: TriggerDevIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TriggerDevIcon} iconColor="" />),
};
