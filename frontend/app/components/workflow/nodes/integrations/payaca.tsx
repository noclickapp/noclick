// Payaca joins the canvas and integration catalog through this definition.
// Its schema and credential metadata are generated from the backend node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PayacaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/payaca.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const PayacaNode: NodeDefinition = {
    type: 'automation-payaca', category: 'industry', label: 'Payaca',
    description: 'Manage customers, projects, invoices and signed Payaca events',
    Icon: PayacaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PayacaIcon} iconColor="" />),
};
