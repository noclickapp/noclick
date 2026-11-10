import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';
import type { CSSProperties } from 'react';

// Unmodified icon mark from https://www.chatwoot.com/brand.
const ChatwootIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/chatwoot.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ChatwootNode: NodeDefinition = {
    type: 'automation-chatwoot',
    label: 'Chatwoot',
    description: 'Manage support contacts, route conversations, send replies and private notes',
    category: 'support',
    keywords: ['support', 'helpdesk', 'customer service', 'live chat'],
    Icon: ChatwootIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: props => <AutomationNode {...props} Icon={ChatwootIcon} iconColor="" />,
};
