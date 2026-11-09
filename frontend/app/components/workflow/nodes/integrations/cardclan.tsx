// Cardclan sends personalized digital cards and reads integration workflows.
// This definition lets the canvas and integration catalog discover its node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CardclanIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/cardclan.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const CardclanNode: NodeDefinition = {
    type: 'automation-cardclan', category: 'communication', label: 'Cardclan',
    description: 'Send personalized digital cards, generate card URLs and manage integration workflows',
    keywords: ['CardClan', 'greeting cards', 'recognition'],
    Icon: CardclanIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CardclanIcon} iconColor="" />),
};
