// Registers CallFire in the workflow canvas and integration catalog.
// The definition uses the official provider icon and generated backend schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CallFireIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/callfire.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const CallFireNode: NodeDefinition = {
    type: 'automation-callfire', category: 'communication', label: 'CallFire',
    description: 'Send texts and calls, manage contacts and lists, and control text broadcasts',
    keywords: ['SMS', 'voice', 'text messaging', 'broadcast'],
    Icon: CallFireIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CallFireIcon} iconColor="" />),
};
