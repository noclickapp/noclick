// Defines InvestorLift in the workflow palette and industry integration catalog.
// Its operations and manual API-key form come from the generated backend schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const InvestorLiftIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/investorlift.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const InvestorLiftNode: NodeDefinition = {
    type: 'automation-investorlift', category: 'industry', label: 'InvestorLift',
    description: 'Underwrite properties and read listings, investors, lenders and transaction history',
    Icon: InvestorLiftIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={InvestorLiftIcon} iconColor="" />),
};
