import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WhatsAbleIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/whatsable-ca185063.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const WhatsAbleNode: NodeDefinition = {
    type: 'automation-whatsable-ca185063', category: 'communication', label: 'WhatsAble',
    description: 'Send and schedule WhatsApp messages, manage contacts and labels, and read conversations and templates',
    keywords: ['WhatsApp', 'Whatsable'],
    Icon: WhatsAbleIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WhatsAbleIcon} iconColor="" />),
};
