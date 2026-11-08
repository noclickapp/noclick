import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SendlaneIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/sendlane.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SendlaneNode: NodeDefinition = {
    type: 'automation-sendlane', label: 'Sendlane',
    description: 'Manage contacts, lists, tags and custom fields; read campaigns and segments',
    keywords: ['email', 'marketing', 'audience', 'subscriber', 'contacts'],
    Icon: SendlaneIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SendlaneIcon} iconColor="" />),
};
