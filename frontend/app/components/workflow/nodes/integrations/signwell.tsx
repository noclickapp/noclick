import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SignwellIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/signwell.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SignwellNode: NodeDefinition = {
    type: 'automation-signwell', category: 'documents', label: 'SignWell',
    description: 'Create and send documents, manage templates, and start workflows from signing events',
    keywords: ['esignature', 'electronic signature', 'Signwell', 'document signing'],
    Icon: SignwellIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SignwellIcon} iconColor="" />),
};
