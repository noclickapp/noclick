import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const IpinfoIoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/ipinfo-io.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const IpinfoIoNode: NodeDefinition = {
    type: 'automation-ipinfo-io', label: 'IPinfo',
    category: 'developer-tools',
    description: 'Enrich IP addresses, check networks and privacy, and generate IP reports',
    Icon: IpinfoIoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={IpinfoIoIcon} iconColor="" />),
};
