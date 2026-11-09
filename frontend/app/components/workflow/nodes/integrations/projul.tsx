import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ProjulIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/projul.svg"
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

export const ProjulNode: NodeDefinition = {
    type: 'automation-projul',
    category: 'industry',
    label: 'Projul',
    keywords: ['construction', 'contractor', 'leads', 'project management'],
    description:
        'Manage construction customers, leads, projects, tasks and internal messages; read estimates and invoices',
    Icon: ProjulIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={ProjulIcon} iconColor="" />
    )),
};
