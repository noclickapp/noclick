// Pledge's charitable giving API supports donations, fundraisers and nonprofit search.
// This definition adds its catalog entry and uses Pledge's official brand icon.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PledgeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/pledge.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const PledgeNode: NodeDefinition = {
    type: 'automation-pledge', category: 'nonprofit', label: 'Pledge',
    description: 'Create donations and fundraisers, find nonprofits, and react to signed donation events',
    keywords: ['charity', 'nonprofit', 'fundraising', 'donations', 'Pledgeling'],
    Icon: PledgeIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PledgeIcon} iconColor="" />),
};
