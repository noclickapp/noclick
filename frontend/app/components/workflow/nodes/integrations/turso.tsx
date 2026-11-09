import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TursoIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/turso.svg"
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

export const TursoNode: NodeDefinition = {
    type: 'automation-turso',
    category: 'databases-storage',
    label: 'Turso',
    description:
        'Manage databases and groups, inspect configuration, instances and usage',
    Icon: TursoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function TursoComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={TursoIcon} iconColor="" />;
    }),
};
