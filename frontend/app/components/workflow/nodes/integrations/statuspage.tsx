import { memo, type CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Unmodified Statuspage icon from Atlassian's official brand download.
const StatuspageIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/statuspage.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const StatuspageNode: NodeDefinition = {
    type: 'automation-statuspage',
    label: 'Statuspage',
    description: 'Manage incidents, components, subscribers and scheduled maintenance',
    category: 'monitoring',
    keywords: ['Atlassian', 'status page', 'outage', 'maintenance'],
    Icon: StatuspageIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={StatuspageIcon} iconColor="" />),
};
