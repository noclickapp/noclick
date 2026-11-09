import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const KickIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/kick.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const KickNode: NodeDefinition = {
    type: 'automation-kick', category: 'media', label: 'Kick',
    description: 'Manage channels, chat, rewards and moderation, and read livestreams',
    Icon: KickIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KickIcon} iconColor="" />),
};
