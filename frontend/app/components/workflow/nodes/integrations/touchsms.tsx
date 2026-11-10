import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TouchSMSIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/touchsms.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TouchSMSNode: NodeDefinition = {
    type: 'automation-touchsms', category: 'communication', label: 'touchSMS',
    description: 'Send SMS and MMS, manage contacts, templates and opt-outs, and read replies',
    Icon: TouchSMSIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TouchSMSIcon} iconColor="" />),
};
