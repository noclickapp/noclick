// DNSFilter's discoverable workflow definition uses the publisher's official icon.
// Configuration and credentials are generated from the backend node schema.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DNSFilterIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/dnsfilter.webp" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
DNSFilterIcon.displayName = 'DNSFilterIcon';

export const DNSFilterNode: NodeDefinition = {
    type: 'automation-dnsfilter',
    label: 'DNSFilter',
    description: 'Manage networks, filtering policies and domain allowlists or blocklists',
    keywords: ['dns', 'dnsfilter', 'web filtering', 'roaming agents', 'security'],
    Icon: DNSFilterIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DNSFilterIcon} iconColor="" />),
};
