import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CleverTapIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/clevertap.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const CleverTapNode: NodeDefinition = {
    type: 'automation-clevertap', category: 'marketing', label: 'CleverTap',
    description: 'Profiles, events, messaging campaigns, subscriptions and user variables',
    Icon: CleverTapIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CleverTapIcon} iconColor="" />),
};
