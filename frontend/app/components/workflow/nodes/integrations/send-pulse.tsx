/** Registers SendPulse in the workflow catalog and canvas. Uses the provider icon and the shared schema-driven configuration UI. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SendPulseIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/send-pulse.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SendPulseNode: NodeDefinition = {
    type: 'automation-send-pulse', category: 'marketing', label: 'SendPulse',
    description: 'Manage mailing lists, subscribers, campaigns and tags',
    Icon: SendPulseIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SendPulseIcon} iconColor="" />),
};
