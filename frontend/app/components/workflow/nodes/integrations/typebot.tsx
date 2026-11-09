import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TypebotIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/typebot.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TypebotNode: NodeDefinition = {
    type: 'automation-typebot', category: 'forms', label: 'Typebot',
    description: 'Manage conversational forms, workspaces, folders, results and analytics',
    keywords: ['chatbot', 'conversational form', 'survey', 'lead capture'],
    Icon: TypebotIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TypebotIcon} iconColor="" />),
};
