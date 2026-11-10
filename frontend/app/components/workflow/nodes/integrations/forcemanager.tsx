import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const ForcemanagerIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/forcemanager.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ForcemanagerIcon.displayName = 'ForcemanagerIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const ForcemanagerNode: NodeDefinition = {
    type: 'automation-forcemanager',
    label: 'ForceManager',
    description: 'Manage CRM accounts, contacts, opportunities, activities and calendar events',
    category: 'crm-sales',
    keywords: ['Sage Sales Management', 'CRM'],
    Icon: ForcemanagerIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ForcemanagerIcon} iconColor="" />),
};
