import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DocusealIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/docuseal.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const DocusealNode: NodeDefinition = {
    type: 'automation-docuseal', category: 'documents', label: 'DocuSeal',
    description: 'Manage document templates, signature submissions and signers',
    Icon: DocusealIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DocusealIcon} iconColor="" />),
};
