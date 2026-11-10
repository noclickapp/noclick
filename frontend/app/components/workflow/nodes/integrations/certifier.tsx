// Certifier workflow integration discovered by the node catalog.
// Uses the shared automation renderer with the official provider mark.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const CertifierIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/certifier.svg" dark="/icons/certifier-dark.svg" className={className} style={style} />
);

export const CertifierNode: NodeDefinition = {
    type: 'automation-certifier', category: 'courses', label: 'Certifier',
    description: 'Create, issue and send credentials; manage templates and designs',
    Icon: CertifierIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CertifierIcon} iconColor="" />),
};
