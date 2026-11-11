import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Elks46Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/46elks.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const Elks46Node: NodeDefinition = {
    type: 'automation-46elks', category: 'communication', label: '46elks',
    description: 'Send and receive SMS and MMS, make calls, and manage numbers and subaccounts',
    Icon: Elks46Icon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Elks46Icon} iconColor="" />),
};
