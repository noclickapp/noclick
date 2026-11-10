import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const PennylaneIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/pennylane.svg" dark="/icons/pennylane-dark.svg" className={className} style={style} />
);

export const PennylaneNode: NodeDefinition = {
    type: 'automation-pennylane', category: 'finance-accounting', label: 'Pennylane',
    description: 'Manage customers, suppliers, invoices, products and bank transactions',
    Icon: PennylaneIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PennylaneIcon} iconColor="" />),
};
