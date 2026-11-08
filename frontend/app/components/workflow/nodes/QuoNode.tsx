import { memo, type CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

// Unmodified official Quo logo from the provider's press / brand page.
const QuoIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/quo.svg"
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

const QuoNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={QuoIcon} iconColor="" />
);

export const QuoNode: NodeDefinition = {
    type: 'automation-quo',
    category: 'communication',
    label: 'Quo',
    keywords: ['OpenPhone', 'SMS', 'CRM', 'call recording', 'transcript'],
    description:
        'Send texts, sync contacts, and retrieve calls, recordings and transcripts',
    Icon: QuoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(QuoNodeComponent),
};
