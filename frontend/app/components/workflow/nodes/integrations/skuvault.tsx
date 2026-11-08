import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SkuVaultIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/skuvault-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
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
