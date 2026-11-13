// Timeero connects workforce records and real-time events to workflows.
// This definition lets the integration catalog and canvas discover its generated schema.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';


const TimeeroIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/timeero.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
TimeeroIcon.displayName = 'TimeeroIcon';

// Official Timeero website icon; provenance is recorded beside the PNG.
export const TimeeroNode: NodeDefinition = {
    type: 'automation-timeero',
    label: 'Timeero',
    description: 'Employees, jobs, tasks, timesheets, schedules and signed webhook triggers',
    category: 'hr-recruiting',
    Icon: TimeeroIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TimeeroIcon} iconColor="" />),
};
