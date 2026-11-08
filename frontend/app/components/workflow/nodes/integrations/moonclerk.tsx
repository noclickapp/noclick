// Register MoonClerk's read-only payment API in the integration catalog.
// The official service icon identifies nodes on the workflow canvas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MoonclerkIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/moonclerk.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const MoonclerkNode: NodeDefinition = {
    type: 'automation-moonclerk', label: 'MoonClerk',
    description: 'Read payment forms, customers, subscriptions and payments',
    Icon: MoonclerkIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MoonclerkIcon} iconColor="" />),
};
