import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GetAcceptIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/getaccept.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const GetAcceptNode: NodeDefinition = {
    type: 'automation-getaccept', category: 'crm-sales', label: 'GetAccept',
    description: 'Create, send and track sales documents, manage contacts and read templates',
    Icon: GetAcceptIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GetAcceptIcon} iconColor="" />),
};
