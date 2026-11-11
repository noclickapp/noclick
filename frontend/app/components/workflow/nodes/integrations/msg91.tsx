import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Msg91Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/msg91.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const Msg91Node: NodeDefinition = {
    type: 'automation-msg91', label: 'MSG91',
    category: 'communication',
    description: 'Watch email delivery and Hello tickets; send SMS, OTP and email; manage templates, reports and contacts',
    Icon: Msg91Icon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Msg91Icon} iconColor="" />),
};
