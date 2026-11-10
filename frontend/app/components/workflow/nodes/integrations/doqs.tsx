import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DoqsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/doqs.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const DoqsNode: NodeDefinition = {
    type: 'automation-doqs', category: 'documents', label: 'Doqs',
    description: 'Fill PDF templates, render HTML to PDF, and list templates and submissions',
    keywords: ['doqs.dev', 'PDF filling', 'document generation', 'HTML to PDF'],
    Icon: DoqsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DoqsIcon} iconColor="" />),
};
