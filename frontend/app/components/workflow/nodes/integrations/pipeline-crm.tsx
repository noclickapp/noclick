import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const PipelineCrmIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/pipeline-crm.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
PipelineCrmIcon.displayName = 'PipelineCrmIcon';

// Exact publisher asset; provenance is recorded beside the image.
export const PipelineCrmNode: NodeDefinition = {
    type: 'automation-pipeline-crm',
    label: 'Pipeline CRM',
    description: 'Deals, people, companies, activities and tasks',
    Icon: PipelineCrmIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PipelineCrmIcon} iconColor="" />),
};
