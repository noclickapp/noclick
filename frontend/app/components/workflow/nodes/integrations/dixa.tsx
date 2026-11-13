// Dixa exposes support actions and internal note notifications on the canvas.
// This definition lets discovery load its generated schema and official icon.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const DixaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/dixa.svg" dark="/icons/dixa-dark.svg" className={className} style={style} />
);

export const DixaNode: NodeDefinition = {
    type: 'automation-dixa', category: 'support', label: 'Dixa',
    description: 'Manage support conversations, contacts, replies, notes and tags',
    keywords: ['customer service', 'helpdesk', 'support'],
    Icon: DixaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DixaIcon} iconColor="" />),
};
