// ClickFunnels lead, purchase and course automation in the workflow palette.
// Uses the unmodified icon published by ClickFunnels on its official brand site.
import type { CSSProperties } from 'react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ClickFunnelsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/clickfunnels.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ClickFunnelsNode: NodeDefinition = {
    type: 'automation-clickfunnels',
    label: 'ClickFunnels',
    description: 'Create and tag leads, sync purchases, and enroll customers in courses',
    category: 'marketing',
    Icon: ClickFunnelsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: props => <AutomationNode {...props} Icon={ClickFunnelsIcon} iconColor="" />,
};
