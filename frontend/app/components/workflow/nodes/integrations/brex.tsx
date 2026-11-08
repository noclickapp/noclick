// Brex's canvas definition is discovered from its integration filename.
// Its component loads only when a Brex node appears on the canvas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Unmodified Brex symbol from Brex's official press kit.
const BrexIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/brex.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={
            {
                ...style,
                '--brand-invert': 0,
                objectFit: 'contain',
            } as CSSProperties
        }
    />
);

const BrexNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={BrexIcon} iconColor="" />
);

export const BrexNode: NodeDefinition = {
    type: 'automation-brex',
    label: 'Brex',
    description: 'Manage expenses, cards, transactions and transfers',
    category: 'finance-accounting',
    keywords: [
        'expenses',
        'corporate cards',
        'payments',
        'transactions',
        'transfers',
    ],
    Icon: BrexIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(BrexNodeComponent),
};
