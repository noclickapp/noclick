import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CorbitSMSIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/corbit-sms.svg" alt="" aria-hidden="true" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const CorbitSMSNode: NodeDefinition = {
    type: 'automation-corbit-sms',
    category: 'communication',
    label: 'Corbit SMS',
    description: 'Send SMS, manage templates, check delivery and monitor new sent messages',
    Icon: CorbitSMSIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CorbitSMSIcon} iconColor="" />),
};
