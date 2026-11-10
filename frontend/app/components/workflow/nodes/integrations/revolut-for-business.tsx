// Revolut Business connects account, accounting and payment workflows.
// The provider icon identifies the service in the canvas and integration catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const RevolutIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/revolut-for-business.svg" dark="/icons/revolut-for-business-dark.svg" className={className} style={style} />
);

export const RevolutBusinessNode: NodeDefinition = {
    type: 'automation-revolut-for-business', category: 'finance-accounting', label: 'Revolut Business',
    description: 'Manage business accounts, transactions, counterparties, expenses, cards and payments',
    keywords: ['Revolut', 'banking', 'payments', 'finance'],
    Icon: RevolutIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RevolutIcon} iconColor="" />),
};
