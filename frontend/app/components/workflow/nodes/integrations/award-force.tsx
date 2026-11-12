// Award Force automates award entries, entrants and judging assignments.
// This definition makes the integration available in the workflow canvas and catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AwardForceIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/award-force.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const AwardForceNode: NodeDefinition = {
    type: 'automation-award-force', category: 'industry', label: 'Award Force',
    description: 'Manage award entries, people and judging assignments',
    keywords: ['awards', 'competitions', 'scholarships', 'judging'],
    Icon: AwardForceIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AwardForceIcon} iconColor="" />),
};
