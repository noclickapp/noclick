import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const NangoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/nango.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const NangoNode: NodeDefinition = {
    type: 'automation-nango', category: 'developer-tools', label: 'Nango',
    description: 'Manage integrations, connections, synced records, syncs and actions',
    Icon: NangoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NangoIcon} iconColor="" />),
};
