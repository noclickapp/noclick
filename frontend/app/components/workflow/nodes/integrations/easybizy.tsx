// Easybizy exposes the business records and scheduling actions used by service teams.
// This definition makes the self-registering node available in the canvas and catalog.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const EasybizyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/easybizy.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
EasybizyIcon.displayName = 'EasybizyIcon';

export const EasybizyNode: NodeDefinition = {
    type: 'automation-easybizy',
    label: 'Easybizy',
    description: 'Manage customers, leads, activity notes, appointments and invoices',
    category: 'crm-sales',
    keywords: ['customers', 'leads', 'appointments', 'scheduling', 'CRM'],
    Icon: EasybizyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EasybizyIcon} iconColor="" />),
};
