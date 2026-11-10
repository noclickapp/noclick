import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TimelinesAIIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/timelinesai.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TimelinesAINode: NodeDefinition = {
    type: 'automation-timelinesai', category: 'communication', label: 'TimelinesAI',
    description: 'Automate WhatsApp chats, messages, labels, files and templates',
    Icon: TimelinesAIIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TimelinesAIIcon} iconColor="" />),
};
