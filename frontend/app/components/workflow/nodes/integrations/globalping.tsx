import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GlobalpingIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/globalping.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const GlobalpingNode: NodeDefinition = {
    type: 'automation-globalping', category: 'monitoring', label: 'Globalping',
    description: 'Run global ping, traceroute, MTR, DNS and HTTP measurements; read results, probes and limits',
    keywords: ['network', 'latency', 'uptime', 'dns', 'ping', 'traceroute'],
    Icon: GlobalpingIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GlobalpingIcon} iconColor="" />),
};
