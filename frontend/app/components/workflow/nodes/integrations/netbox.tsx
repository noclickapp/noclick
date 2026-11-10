import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const NetBoxIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/netbox.svg" alt="" className={className} style={style} {...props} />
    ),
);
NetBoxIcon.displayName = 'NetBoxIcon';

export const NetBoxNode: NodeDefinition = {
    type: 'automation-netbox',
    label: 'NetBox API',
    description: 'Manage network devices, sites, interfaces, IP addresses, prefixes and virtual machines',
    category: 'developer-tools',
    Icon: NetBoxIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NetBoxIcon} iconColor="" />),
};
