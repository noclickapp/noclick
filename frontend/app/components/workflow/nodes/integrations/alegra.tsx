// Alegra's sales tools and event triggers use the standard automation node UI.
// This definition adds the service to the finance and accounting catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AlegraIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/alegra.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const AlegraNode: NodeDefinition = {
    type: 'automation-alegra', category: 'finance-accounting', label: 'Alegra',
    description: 'Manage invoices, payments, credit notes and estimates; react to new invoices, clients and items',
    Icon: AlegraIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AlegraIcon} iconColor="" />),
};
