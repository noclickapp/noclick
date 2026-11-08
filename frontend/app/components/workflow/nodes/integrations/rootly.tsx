// Rootly incident response actions appear in the canvas and integration catalog.
// The icon is the official asset published in Rootly's API contract.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RootlyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/rootly.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const RootlyNode: NodeDefinition = {
    type: 'automation-rootly', label: 'Rootly',
    category: 'developer-tools',
    description: 'Manage incidents, timeline events and action items; look up teams, services and users',
    Icon: RootlyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RootlyIcon} iconColor="" />),
};
