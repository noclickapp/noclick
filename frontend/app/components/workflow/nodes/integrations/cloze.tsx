// Adds Cloze CRM to the workflow canvas and integration catalog.
// Its schema is generated from the backend; the icon is the official publisher asset.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const ClozeIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/cloze.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ClozeIcon.displayName = 'ClozeIcon';


export const ClozeNode: NodeDefinition = {
    type: 'automation-cloze',
    label: 'Cloze',
    description: 'Manage contacts, companies, projects, tasks and notes',
    category: 'crm-sales',
    Icon: ClozeIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ClozeIcon} iconColor="" />),
};
