import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TeamworkDeskIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/teamwork-desk.svg"
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

export const TeamworkDeskNode: NodeDefinition = {
    type: 'automation-teamwork-desk',
    category: 'support',
    label: 'Teamwork Desk',
    description:
        'Create and update support tickets, replies, customers, companies and tags',
    Icon: TeamworkDeskIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function TeamworkDeskComponent(props: NodeProps) {
        return (
            <AutomationNode {...props} Icon={TeamworkDeskIcon} iconColor="" />
        );
    }),
};
