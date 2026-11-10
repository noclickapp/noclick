import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const RundeckIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/rundeck.svg" alt="" className={className} style={style} {...props} />
    ),
);
RundeckIcon.displayName = 'RundeckIcon';

export const RundeckNode: NodeDefinition = {
    type: 'automation-rundeck',
    label: 'Rundeck',
    description: 'Run jobs, manage schedules, inspect executions and watch completions',
    category: 'developer-tools',
    keywords: ['runbook', 'jobs', 'operations', 'PagerDuty Runbook Automation'],
    Icon: RundeckIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RundeckIcon} iconColor="" />),
};
