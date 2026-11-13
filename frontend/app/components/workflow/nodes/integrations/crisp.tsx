import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';
import type { CSSProperties } from 'react';

// Crisp's speech-bubble mark from its site header logo (provenance beside the icon).
const CrispIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/crisp.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CrispNode: NodeDefinition = {
    type: 'automation-crisp',
    label: 'Crisp',
    description: 'Answer website chats: wake on visitor messages, reply, add notes, resolve and assign conversations',
    category: 'support',
    keywords: ['live chat', 'website chat', 'chat widget', 'support inbox', 'helpdesk', 'customer service'],
    Icon: CrispIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: props => <AutomationNode {...props} Icon={CrispIcon} iconColor="" />,
};
