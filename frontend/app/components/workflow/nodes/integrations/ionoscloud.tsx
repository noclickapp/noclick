// IONOS Cloud reads approved datacenter and server metadata.
// This native editor definition displays the original official cloud favicon.
import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
const IONOSCloudIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/ionoscloud.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />,
);
IONOSCloudIcon.displayName = 'IONOSCloudIcon';
export const IONOSCloudNode: NodeDefinition = {
    type: 'automation-ionoscloud', label: 'IONOS Cloud',
    description: 'Read scoped datacenter and server metadata',
    keywords: ['ionoscloud', 'cloud', 'datacenters', 'servers'],
    Icon: IONOSCloudIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={IONOSCloudIcon} iconColor="" />),
};
