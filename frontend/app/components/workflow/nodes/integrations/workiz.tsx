import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const WorkizIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/workiz.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
WorkizIcon.displayName = 'WorkizIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const WorkizNode: NodeDefinition = {
    type: 'automation-workiz',
    label: 'Workiz',
    description: 'Manage jobs, leads, clients, notes and invoices',
    category: 'industry',
    Icon: WorkizIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WorkizIcon} iconColor="" />),
};
