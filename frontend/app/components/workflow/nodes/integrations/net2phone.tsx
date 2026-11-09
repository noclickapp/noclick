import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Net2PhoneIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/net2phone.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);
export const Net2PhoneNode: NodeDefinition = {
    type: 'automation-net2phone', category: 'communication', label: 'net2phone',
    description: 'Place calls, read call records and users, and react to call events',
    keywords: ['phone', 'telephony', 'calls', 'cdr', 'net2phone'],
    Icon: Net2PhoneIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Net2PhoneIcon} iconColor="" />),
};
