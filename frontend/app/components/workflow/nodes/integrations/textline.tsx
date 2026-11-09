// Textline's self-registering definition exposes its messaging and contact actions.
// The provider's official favicon identifies the account throughout the workflow UI.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TextlineIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/textline.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TextlineNode: NodeDefinition = {
    type: 'automation-textline', category: 'communication', label: 'Textline',
    description: 'Send and schedule texts, manage conversations, and update contacts',
    keywords: ['SMS', 'text messages', 'business texting', 'contacts', 'whisper'],
    Icon: TextlineIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TextlineIcon} iconColor="" />),
};
