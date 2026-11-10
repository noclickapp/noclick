import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const Cin7CoreIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/cin7-core.svg" dark="/icons/cin7-core-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
Cin7CoreIcon.displayName = 'Cin7CoreIcon';

export const Cin7CoreNode: NodeDefinition = {
    type: 'automation-cin7-core', category: 'ecommerce', label: 'Cin7 Core Inventory',
    keywords: ['DEAR Inventory', 'stock', 'warehouse', 'products', 'suppliers'],
    description: 'Manage products, customers, suppliers and stock adjustments; read sales and purchases',
    Icon: Cin7CoreIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Cin7CoreIcon} iconColor="" />),
};
