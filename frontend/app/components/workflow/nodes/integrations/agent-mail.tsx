import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const AgentMailIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/agent-mail.svg" dark="/icons/agent-mail-dark.svg" className={className} style={style} />
);

export const AgentMailNode: NodeDefinition = {
    type: 'automation-agent-mail', category: 'communication', label: 'AgentMail',
    description: 'Create inboxes, send and reply to email, manage threads and drafts',
    Icon: AgentMailIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AgentMailIcon} iconColor="" />),
};
