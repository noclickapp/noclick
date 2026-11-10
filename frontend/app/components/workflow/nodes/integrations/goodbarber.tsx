// Displays the GoodBarber Commerce integration in the catalog and canvas.
// Uses the official provider logo to make connected shops recognizable.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GoodBarberIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/goodbarber.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const GoodBarberNode: NodeDefinition = {
    type: 'automation-goodbarber', category: 'ecommerce', label: 'GoodBarber',
    description: 'Automate shop products, customers, orders and shipping',
    Icon: GoodBarberIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GoodBarberIcon} iconColor="" />),
};
