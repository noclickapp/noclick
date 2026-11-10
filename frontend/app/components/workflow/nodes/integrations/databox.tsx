import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DataboxIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/databox.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const DataboxNode: NodeDefinition = {
    type: 'automation-databox', category: 'analytics-bi', label: 'Databox',
    description: 'Manage datasets, ingest records, read metrics and automate dashboards',
    Icon: DataboxIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DataboxIcon} iconColor="" />),
};
