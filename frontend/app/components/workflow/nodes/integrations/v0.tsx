import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const V0Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/v0.svg" dark="/icons/v0-dark.svg" className={className} style={style} />
);

export const V0Node: NodeDefinition = {
    type: 'automation-v0', category: 'ai', label: 'V0',
    description: 'Generate apps, manage chats and files, deploy, and subscribe to webhooks',
    Icon: V0Icon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={V0Icon} iconColor="" />),
};
