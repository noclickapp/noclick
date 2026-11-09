import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SMSGlobalIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/smsglobal.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SMSGlobalNode: NodeDefinition = {
    type: 'automation-smsglobal', category: 'communication', label: 'SMSGlobal',
    description: 'Send SMS, manage contacts and groups, monitor incoming messages and delivery status',
    Icon: SMSGlobalIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SMSGlobalIcon} iconColor="" />),
};
