import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RocketadminIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/rocketadmin.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const RocketadminNode: NodeDefinition = {
    type: 'automation-rocketadmin', category: 'databases-storage', label: 'Rocketadmin',
    description: 'Discover database connections and tables, read schemas, filter rows, and create, update or delete records.',
    keywords: ['database', 'admin panel', 'rows', 'CRUD', 'SQL'],
    Icon: RocketadminIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RocketadminIcon} iconColor="" />),
};
