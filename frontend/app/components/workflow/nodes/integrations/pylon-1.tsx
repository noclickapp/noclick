import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PylonIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/pylon-1.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const PylonNode: NodeDefinition = {
    type: 'automation-pylon-1', category: 'support', label: 'Pylon',
    description: 'Manage Pylon support issues, messages, accounts, contacts and tags',
    Icon: PylonIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PylonIcon} iconColor="" />),
};
