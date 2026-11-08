// Certifier workflow integration discovered by the node catalog.
// Uses the shared automation renderer with the official provider mark.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CertifierIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/certifier.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const CertifierNode: NodeDefinition = {
    type: 'automation-certifier', label: 'Certifier',
    description: 'Create, issue and send credentials; manage templates and designs',
    Icon: CertifierIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CertifierIcon} iconColor="" />),
};
