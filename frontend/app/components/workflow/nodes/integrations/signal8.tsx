import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Signal8Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/signal8.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`} style={style} />
        <img src="/icons/signal8-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`} style={style} />
    </>
);

export const Signal8Node: NodeDefinition = {
    type: 'automation-signal8', category: 'finance-accounting', label: 'Signal8',
    description: 'Research stocks, dilution risk, ownership and SEC filings; watch new filings',
    keywords: ['stocks', 'SEC', 'EDGAR', 'dilution', 'market data'],
    Icon: Signal8Icon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Signal8Icon} iconColor="" />),
};
