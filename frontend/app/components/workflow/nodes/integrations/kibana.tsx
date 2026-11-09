import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const KibanaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/kibana.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const KibanaNode: NodeDefinition = {
    type: 'automation-kibana', category: 'monitoring', label: 'Kibana',
    description: 'Manage Kibana data views, spaces, alert rules and connectors',
    Icon: KibanaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KibanaIcon} iconColor="" />),
};
