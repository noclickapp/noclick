import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const Signal8Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/signal8.svg" dark="/icons/signal8-dark.svg" className={className} style={style} />
);

export const Signal8Node: NodeDefinition = {
    type: 'automation-signal8', category: 'finance-accounting', label: 'Signal8',
    description: 'Research stocks, dilution risk, ownership and SEC filings; watch new filings',
    keywords: ['stocks', 'SEC', 'EDGAR', 'dilution', 'market data'],
    Icon: Signal8Icon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Signal8Icon} iconColor="" />),
};
