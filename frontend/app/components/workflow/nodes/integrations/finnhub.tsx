import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FinnhubIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/finnhub.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const FinnhubNode: NodeDefinition = {
    type: 'automation-finnhub', category: 'finance-accounting', label: 'Finnhub',
    description: 'Read market data, fundamentals and news, and query AI Copilot',
    Icon: FinnhubIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FinnhubIcon} iconColor="" />),
};
