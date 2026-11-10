// Adds Linode instance and DNS automation to the workflow palette.
// The provider icon is kept byte for byte with its provenance sidecar.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const LinodeIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/linode.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
LinodeIcon.displayName = 'LinodeIcon';

export const LinodeNode: NodeDefinition = {
    type: 'automation-linode',
    label: 'Linode',
    description: 'Manage cloud instances, DNS records, images, volumes and events',
    category: 'cloud-hosting',
    keywords: ['Akamai', 'cloud', 'hosting', 'VPS', 'DNS'],
    Icon: LinodeIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LinodeIcon} iconColor="" />),
};
