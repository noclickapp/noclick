import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const GotifyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/gotify.svg" dark="/icons/gotify-dark.svg" className={className} style={style} />
);

export const GotifyNode: NodeDefinition = {
    type: 'automation-gotify', category: 'communication', label: 'Gotify',
    description: 'Send notifications, manage applications and clients, and trigger on new messages',
    keywords: ['push', 'notifications', 'self hosted', 'alerts'],
    Icon: GotifyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GotifyIcon} iconColor="" />),
};
