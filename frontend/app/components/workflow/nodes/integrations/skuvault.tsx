import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const SkuVaultIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/skuvault-brand-vector.svg" dark="/icons/skuvault-brand-vector-dark.svg" className={className} style={style} />
);
const SkuVaultComponent = (props: NodeProps) => <AutomationNode {...props} Icon={SkuVaultIcon} iconColor="" />;
export const SkuVaultNode: NodeDefinition = {
    type: 'automation-skuvault',
    label: 'SkuVault',
    description: 'Product, kit, warehouse and inventory metadata; selected catalog changes',
    category: 'ecommerce',
    Icon: SkuVaultIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(SkuVaultComponent),
};
