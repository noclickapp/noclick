import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const V0Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/v0.svg" alt="" aria-hidden="true" className={`brand-mono ${className ?? ''}`}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const V0Node: NodeDefinition = {
    type: 'automation-v0', category: 'ai', label: 'V0',
    description: 'Generate apps, manage chats and files, deploy, and subscribe to webhooks',
    Icon: V0Icon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={V0Icon} iconColor="" />),
};
