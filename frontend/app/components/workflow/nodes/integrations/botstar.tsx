import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BotstarIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/botstar.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const BotstarNode: NodeDefinition = {
    type: 'automation-botstar', category: 'communication', label: 'BotStar',
    description: 'Manage chatbots, audience profiles and CMS content, and send Facebook messages',
    keywords: ['botstar', 'chatbot', 'messenger', 'audience', 'cms'],
    Icon: BotstarIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BotstarIcon} iconColor="" />),
};
