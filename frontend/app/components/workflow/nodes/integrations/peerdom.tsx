import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PeerdomIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/peerdom.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const PeerdomNode: NodeDefinition = {
    type: 'automation-peerdom',
    category: 'hr-recruiting',
    label: 'Peerdom',
    description: 'Manage peers, roles, circles, role holders and projects',
    keywords: ['organization', 'org chart', 'circles', 'teams', 'people', 'responsibilities'],
    Icon: PeerdomIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PeerdomIcon} iconColor="" />),
};
