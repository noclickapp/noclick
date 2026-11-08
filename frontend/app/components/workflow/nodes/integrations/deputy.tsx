import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const DeputyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/deputy.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
DeputyIcon.displayName = 'DeputyIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const DeputyNode: NodeDefinition = {
    type: 'automation-deputy',
    label: 'Deputy',
    keywords: ['workforce', 'scheduling', 'roster', 'shifts', 'clock in', 'clock out', 'leave'],
    description: 'Automate employees, locations, shifts, timesheets, leave and tasks',
    Icon: DeputyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DeputyIcon} iconColor="" />),
};
