import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Ip2ProxyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/ip2proxy.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const Ip2ProxyNode: NodeDefinition = {
    type: 'automation-ip2proxy', category: 'developer-tools', label: 'IP2Proxy',
    description: 'Detect proxies, VPNs and threats using eleven IP2Proxy package queries',
    keywords: ['ip', 'vpn', 'tor', 'proxy', 'fraud', 'geolocation', 'ip2proxy'],
    Icon: Ip2ProxyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Ip2ProxyIcon} iconColor="" />),
};
