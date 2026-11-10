import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const IplocateIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/iplocate.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const IplocateNode: NodeDefinition = {
    type: 'automation-iplocate', category: 'developer-tools', label: 'IPLocate',
    description: 'Look up IP geolocation, ASN, company and threat intelligence individually or in batches',
    keywords: ['geoip', 'ip address', 'vpn', 'proxy', 'asn'],
    Icon: IplocateIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={IplocateIcon} iconColor="" />),
};
