import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

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
