import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ZulipIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/zulip.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ZulipNode: NodeDefinition = {
    type: 'automation-zulip', label: 'Zulip',
    description: 'Send and manage messages, reactions, channels, subscriptions and users',
    Icon: ZulipIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZulipIcon} iconColor="" />),
};
