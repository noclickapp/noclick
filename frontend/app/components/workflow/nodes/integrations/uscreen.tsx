import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const UscreenIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/uscreen.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const UscreenNode: NodeDefinition = {
    type: 'automation-uscreen', category: 'courses', label: 'Uscreen',
    description: 'Manage customers, subscriptions, content access and video membership reporting',
    Icon: UscreenIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={UscreenIcon} iconColor="" />),
};
