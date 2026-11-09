import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TailscaleIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/tailscale.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TailscaleNode: NodeDefinition = {
    type: 'automation-tailscale', category: 'developer-tools', label: 'Tailscale',
    description: 'Manage tailnet devices, subnet routes, DNS, users and key metadata',
    keywords: ['VPN', 'network', 'MagicDNS', 'subnet router', 'zero trust'],
    Icon: TailscaleIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TailscaleIcon} iconColor="" />),
};
