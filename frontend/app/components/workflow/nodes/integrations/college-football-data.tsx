import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CollegeFootballDataIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/college-football-data.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CollegeFootballDataNode: NodeDefinition = {
    type: 'automation-college-football-data', category: 'industry', label: 'College Football Data',
    description: 'Read football schedules, scores, teams, rankings, recruiting and statistics',
    keywords: ['CFBD', 'NCAA', 'sports', 'college football'],
    Icon: CollegeFootballDataIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CollegeFootballDataIcon} iconColor="" />),
};
