// Creem catalog and customer operations use the shared automation renderer.
// This definition lets the canvas and catalog discover the integration locally.
import { memo, forwardRef, type ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
export const CreemIcon = forwardRef<HTMLImageElement, Pick<ImgHTMLAttributes<HTMLImageElement>, 'className' | 'style'>>(({ className, style }, ref) => (
    <ThemedBrandImg light="/icons/creem.svg" dark="/icons/creem-dark.svg" className={className} style={style} ref={ref} />
));
CreemIcon.displayName = 'CreemIcon';
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={CreemIcon} iconColor="" />;
export const CreemNode: NodeDefinition = {
    type: 'automation-creem', category: 'finance-accounting', label: 'Creem',
    description: 'Manage product and customer records and read subscription, order and license metadata',
    Icon: CreemIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(Component),
};
