import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CallerapiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/callerapi.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CallerapiNode: NodeDefinition = {
    type: 'automation-callerapi', category: 'communication', label: 'CallerAPI',
    description: 'Look up phone intelligence, screen transcripts and monitor phone number reputation',
    keywords: ['callerapi', 'spam', 'phone', 'DID', 'voice', 'fraud'],
    Icon: CallerapiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CallerapiIcon} iconColor="" />),
};
