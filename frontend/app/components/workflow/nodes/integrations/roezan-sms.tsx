import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RoezanSMSIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/roezan-sms.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const RoezanSMSNode: NodeDefinition = {
    type: 'automation-roezan-sms', category: 'communication', label: 'Roezan SMS',
    description: 'Send SMS and MMS, manage contacts, lists and tags, and automate broadcasts',
    keywords: ['text messages', 'messaging', 'broadcasts', 'Roezan'],
    Icon: RoezanSMSIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RoezanSMSIcon} iconColor="" />),
};
