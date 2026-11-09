// Ignition's Core API automates practice clients, services, proposals and billing reads.
// This definition lets the canvas and integration catalog discover the node.
import { forwardRef, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const IgnitionIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/ignition.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
IgnitionIcon.displayName = 'IgnitionIcon';

export const IgnitionNode: NodeDefinition = {
    type: 'automation-ignition',
    label: 'Ignition',
    description: 'Sync clients and contacts, manage services and proposals, and read invoices and payments.',
    category: 'finance-accounting',
    keywords: ['practice ignition', 'accounting', 'engagement', 'proposal', 'client', 'invoice'],
    Icon: IgnitionIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={IgnitionIcon} iconColor="" />),
};
