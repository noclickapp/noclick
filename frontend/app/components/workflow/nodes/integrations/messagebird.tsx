// Registers MessageBird in the integration catalog and workflow canvas.
// Discovery reads this definition without a shared registry entry.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const MessageBirdIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/messagebird.svg" className={className} style={style} />
);

export const MessageBirdNode: NodeDefinition = {
    type: 'automation-messagebird', category: 'communication', label: 'MessageBird',
    description: 'Send, schedule, search and cancel SMS messages; watch new messages and delivery status',
    keywords: ['sms', 'text message', 'bird'], Icon: MessageBirdIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MessageBirdIcon} iconColor="" />),
};
