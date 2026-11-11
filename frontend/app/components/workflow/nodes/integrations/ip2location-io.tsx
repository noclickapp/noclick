import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Ip2LocationIoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/ip2location-io.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const Ip2LocationIoNode: NodeDefinition = {
    type: 'automation-ip2location-io', category: 'content-research', label: 'IP2Location.io',
    description: 'Look up IPv4 and IPv6 geolocation and proxy data',
    Icon: Ip2LocationIoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Ip2LocationIoIcon} iconColor="" />),
};
