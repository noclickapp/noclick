import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const ProxiedmailIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/proxiedmail.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ProxiedmailIcon.displayName = 'ProxiedmailIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const ProxiedmailNode: NodeDefinition = {
    type: 'automation-proxiedmail',
    label: 'ProxiedMail',
    description: 'Manage proxy email addresses, forwarding and received messages',
    category: 'communication',
    Icon: ProxiedmailIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ProxiedmailIcon} iconColor="" />),
};
