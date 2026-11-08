import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FixerIoIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/fixer-io.png"
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

export const FixerIoNode: NodeDefinition = {
    type: 'automation-fixer-io',
    category: 'finance-accounting',
    label: 'Fixer Io',
    description:
        'Read exchange rates, convert currencies, and track historical changes',
    Icon: FixerIoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function FixerIoWorkflowNode(props: NodeProps) {
        return <AutomationNode {...props} Icon={FixerIoIcon} iconColor="" />;
    }),
};
