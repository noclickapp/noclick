import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const InvestorBaseIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/investorbase.svg"
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

export const InvestorBaseNode: NodeDefinition = {
    type: 'automation-investorbase',
    category: 'industry',
    label: 'InvestorBase',
    description:
        'Research property buyers, comparable sales and investor markets; manage enterprise users',
    Icon: InvestorBaseIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function InvestorBaseNodeComponent(props: NodeProps) {
        return (
            <AutomationNode {...props} Icon={InvestorBaseIcon} iconColor="" />
        );
    }),
};
