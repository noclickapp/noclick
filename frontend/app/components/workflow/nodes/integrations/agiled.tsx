import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const AgiledIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/agiled.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
AgiledIcon.displayName = 'AgiledIcon';

// Exact publisher application favicon; provenance is recorded beside the SVG.
export const AgiledNode: NodeDefinition = {
    type: 'automation-agiled',
    label: 'Agiled',
    description: 'Manage contacts, accounts, deals, projects and tasks',
    category: 'crm-sales',
    Icon: AgiledIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AgiledIcon} iconColor="" />),
};
