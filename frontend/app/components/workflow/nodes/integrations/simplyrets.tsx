import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SimplyRETSIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/simplyrets.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={
            {
                ...style,
                objectFit: 'contain',
            } as CSSProperties
        }
    />
);

export const SimplyRETSNode: NodeDefinition = {
    type: 'automation-simplyrets',
    category: 'industry',
    label: 'SimplyRETS',
    description:
        'Search MLS listings, open houses, agents and offices, read analytics and monitor listing changes',
    Icon: SimplyRETSIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={SimplyRETSIcon} iconColor="" />
    )),
};
