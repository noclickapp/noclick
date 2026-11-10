// Revolut Business connects account, accounting and payment workflows.
// The provider icon identifies the service in the canvas and integration catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RevolutIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/revolut-for-business.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' }} />
        <img src="/icons/revolut-for-business-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' }} />
    </>
);

export const RevolutBusinessNode: NodeDefinition = {
    type: 'automation-revolut-for-business', category: 'finance-accounting', label: 'Revolut Business',
    description: 'Manage business accounts, transactions, counterparties, expenses, cards and payments',
    keywords: ['Revolut', 'banking', 'payments', 'finance'],
    Icon: RevolutIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RevolutIcon} iconColor="" />),
};
