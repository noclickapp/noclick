import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MarketSharpIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/marketsharp.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const MarketSharpNode: NodeDefinition = {
    type: 'automation-marketsharp', category: 'crm-sales', label: 'MarketSharp',
    description: 'Automate CRM contacts, opportunities, appointments, estimates and lead sources',
    Icon: MarketSharpIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MarketSharpIcon} iconColor="" />),
};
