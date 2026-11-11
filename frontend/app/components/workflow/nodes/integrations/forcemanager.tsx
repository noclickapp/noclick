import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';


const ForcemanagerIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg {...props} light="/icons/forcemanager.svg" dark="/icons/forcemanager-dark.svg" ref={ref} className={className} style={{ ...style, objectFit: 'contain' }} />
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
