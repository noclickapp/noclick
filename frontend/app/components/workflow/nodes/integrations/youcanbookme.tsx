// YouCanBookMe metadata reads are discovered through this integration definition.
// The official wordmark identifies the provider and preserves its aspect ratio.
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const YouCanBookMeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/youcanbookme.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const YouCanBookMeNode: NodeDefinition = {
    type: 'automation-youcanbookme',
    label: 'YouCanBookMe',
    description: 'Account profiles, team members, appointment types and bounded booking metadata queries.',
    category: 'bookings',
    Icon: YouCanBookMeIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={YouCanBookMeIcon} iconColor="" />,
};
