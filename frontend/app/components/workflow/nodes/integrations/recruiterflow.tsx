import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const RecruiterflowIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/recruiterflow.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
RecruiterflowIcon.displayName = 'RecruiterflowIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const RecruiterflowNode: NodeDefinition = {
    type: 'automation-recruiterflow',
    label: 'Recruiterflow',
    description: 'Manage candidates, contacts, companies, jobs and campaigns',
    category: 'hr-recruiting',
    Icon: RecruiterflowIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RecruiterflowIcon} iconColor="" />),
};
