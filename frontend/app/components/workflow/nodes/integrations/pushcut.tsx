import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PushcutIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/pushcut.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const PushcutNode: NodeDefinition = {
    type: 'automation-pushcut', category: 'productivity', label: 'Pushcut',
    description: 'Send notifications, run iOS automations, manage online actions and update widgets',
    Icon: PushcutIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PushcutIcon} iconColor="" />),
};
