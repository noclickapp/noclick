import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SignwellIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/signwell.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SignwellNode: NodeDefinition = {
    type: 'automation-signwell', category: 'documents', label: 'SignWell',
    description: 'Create and send documents, manage templates and webhooks, and track bulk sends',
    keywords: ['esignature', 'electronic signature', 'Signwell', 'document signing'],
    Icon: SignwellIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SignwellIcon} iconColor="" />),
};
