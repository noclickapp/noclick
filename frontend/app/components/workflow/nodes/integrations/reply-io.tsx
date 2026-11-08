import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ReplyIoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/reply-io.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ReplyIoNode: NodeDefinition = {
    type: 'automation-reply-io', label: 'Reply Io',
    description: 'Manage contacts, contact lists, outreach sequences and tasks',
    Icon: ReplyIoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ReplyIoIcon} iconColor="" />),
};
