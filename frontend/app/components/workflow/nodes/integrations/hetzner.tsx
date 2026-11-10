import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HetznerIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/hetzner.svg" alt="" aria-hidden="true" className={className} style={style} />
);

export const HetznerNode: NodeDefinition = {
    type: 'automation-hetzner', category: 'cloud-hosting', label: 'Hetzner Cloud',
    description: 'Manage cloud servers, snapshots, SSH keys, volumes and firewalls; watch new servers.',
    keywords: ['hetzner', 'hcloud', 'vps', 'cloud hosting', 'server', 'snapshot'],
    Icon: HetznerIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HetznerIcon} iconColor="" />),
};
