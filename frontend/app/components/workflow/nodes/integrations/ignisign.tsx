import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const IgnisignIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/ignisign.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const IgnisignNode: NodeDefinition = {
    type: 'automation-ignisign', category: 'documents', label: 'Ignisign',
    description: 'Manage signers, documents, signature requests and webhooks',
    Icon: IgnisignIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={IgnisignIcon} iconColor="" />),
};
