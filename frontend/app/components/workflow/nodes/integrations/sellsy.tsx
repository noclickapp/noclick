import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const SellsyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/sellsy.svg" dark="/icons/sellsy-dark.svg" className={className} style={style} />
);

export const SellsyNode: NodeDefinition = {
    type: 'automation-sellsy', category: 'crm-sales', label: 'Sellsy',
    description: 'Manage companies, contacts, individuals and opportunities in Sellsy CRM',
    Icon: SellsyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SellsyIcon} iconColor="" />),
};
