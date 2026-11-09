// Registers vcita in the workflow canvas and integration catalog.
// Its CRM & Sales category and official icon keep the new integration discoverable.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const VcitaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/vcita.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const VcitaNode: NodeDefinition = {
    type: 'automation-vcita', category: 'crm-sales', label: 'vcita',
    description: 'Manage clients and bookings; read appointments, availability, services, invoices and payments',
    Icon: VcitaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VcitaIcon} iconColor="" />),
};
