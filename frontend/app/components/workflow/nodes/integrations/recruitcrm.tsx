import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const RecruitCRMIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/recruitcrm.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
RecruitCRMIcon.displayName = 'RecruitCRMIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const RecruitCRMNode: NodeDefinition = {
    type: 'automation-recruitcrm',
    label: 'Recruit CRM',
    description: 'Manage candidates, companies, contacts, jobs, hiring stages, notes and tasks',
    category: 'hr-recruiting',
    Icon: RecruitCRMIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RecruitCRMIcon} iconColor="" />),
};
