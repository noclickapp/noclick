// Resource Guru's self-registering scheduling integration and brand icon.
// This definition supplies its catalog category and lazy canvas component.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ResourceGuruIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/resource-guru.png"
        alt=""
        aria-hidden="true"
        className={className}
        style={
            {
                ...style,
                objectFit: 'contain',
                '--brand-invert': 0,
            } as CSSProperties
        }
    />
);
export const ResourceGuruNode: NodeDefinition = {
    type: 'automation-resource-guru',
    label: 'Resource Guru',
    description:
        'Manage bookings, clients, projects, resources and time off; react to signed client changes',
    category: 'productivity',
    keywords: ['resource scheduling', 'capacity', 'time off', 'booking'],
    Icon: ResourceGuruIcon,
    iconColor: 'text-green-500',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function ResourceGuruComponent(props: NodeProps) {
        return (
            <AutomationNode
                {...props}
                Icon={ResourceGuruIcon}
                iconColor="text-green-500"
            />
        );
    }),
};
