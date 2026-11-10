import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OpendatasoftIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/opendatasoft.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const OpendatasoftNode: NodeDefinition = {
    type: 'automation-opendatasoft', category: 'analytics-bi', label: 'Opendatasoft',
    description: 'Query, export and monitor Opendatasoft datasets and records',
    Icon: OpendatasoftIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OpendatasoftIcon} iconColor="" />),
};
