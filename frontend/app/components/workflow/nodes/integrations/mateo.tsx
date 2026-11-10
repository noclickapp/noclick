// Mateo exposes contact, sales and messaging automations through its legacy API.
// This definition makes the self-registering integration available on the canvas and in the catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MateoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/mateo.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const MateoNode: NodeDefinition = {
    type: 'automation-mateo', category: 'communication', label: 'Mateo',
    description: 'Manage contacts, lists, deals and messages, and receive contact and form events',
    Icon: MateoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MateoIcon} iconColor="" />),
};
