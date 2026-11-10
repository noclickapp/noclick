import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SMSAPIIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/smsapi.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);
export const SMSAPINode: NodeDefinition = {
    type: 'automation-smsapi', category: 'communication', label: 'SMSAPI',
    description: 'Send SMS and manage contacts, groups, sender names and templates',
    Icon: SMSAPIIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SMSAPIIcon} iconColor="" />),
};
