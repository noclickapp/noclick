// YNAB's node definition makes the self-registering integration discoverable.
// The shared automation renderer uses the generated backend configuration schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const YnabIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/ynab.svg" alt="" aria-hidden="true" className={(className || '') + ' [--brand-invert:0] dark:[--brand-invert:1]'}
        style={{ ...style, objectFit: 'contain' }} />
);

export const YnabNode: NodeDefinition = {
    type: 'automation-ynab', category: 'finance-accounting', label: 'YNAB',
    description: 'Manage plans, accounts, categories, payees and transactions',
    keywords: ['You Need A Budget', 'budget', 'personal finance', 'recurring transactions'],
    Icon: YnabIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={YnabIcon} iconColor="" />),
};
