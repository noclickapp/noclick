// Microsoft Entra ID directory actions use the shared automation-node renderer.
// The publisher's Entra icon identifies this integration in the catalog and canvas.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const EntraIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/microsoft-entra-id.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
EntraIcon.displayName = 'EntraIcon';

export const MicrosoftEntraIdNode: NodeDefinition = {
    type: 'automation-microsoft-entra-id',
    label: 'Microsoft Entra ID',
    description: 'Manage directory users, security groups, memberships and tenant inventory',
    Icon: EntraIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EntraIcon} iconColor="" />),
};
