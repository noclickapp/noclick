// Textmagic uses its published brand icon and the shared automation editor.
// This definition makes the self-registering integration discoverable in Communication.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TextmagicIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/textmagic.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TextmagicNode: NodeDefinition = {
    type: 'automation-textmagic', category: 'communication', label: 'Textmagic',
    description: 'Send SMS, manage contacts and lists, read replies and reuse templates',
    keywords: ['SMS', 'text messages', 'Text Magic'],
    Icon: TextmagicIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TextmagicIcon} iconColor="" />),
};
