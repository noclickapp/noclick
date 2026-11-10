import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const TheOddsAPIIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/the-odds-api.svg" className={className} style={style} />
);

export const TheOddsAPINode: NodeDefinition = {
    type: 'automation-the-odds-api', category: 'industry', label: 'The Odds API',
    description: 'Read sports, odds, scores, markets, participants and historical snapshots',
    Icon: TheOddsAPIIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TheOddsAPIIcon} iconColor="" />),
};
