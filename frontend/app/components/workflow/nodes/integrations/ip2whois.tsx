import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Ip2WhoisIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/ip2whois.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const Ip2WhoisNode: NodeDefinition = {
    type: 'automation-ip2whois', category: 'content-research', label: 'IP2WHOIS',
    description: 'Look up domain WHOIS records, contacts, registrar and nameservers',
    keywords: ['whois', 'domain', 'registrar', 'ip2whois'],
    Icon: Ip2WhoisIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Ip2WhoisIcon} iconColor="" />),
};
