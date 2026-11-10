// Greenhouse registers itself with the integration catalog and lazy canvas loader.
// Its definition stays beside its own generated metadata, avoiding shared registry edits.
import { forwardRef, type CSSProperties, type ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GreenhouseIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/greenhouse-brand-vector.svg" alt="" aria-hidden="true"
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
    ),
);
GreenhouseIcon.displayName = 'GreenhouseIcon';
const GreenhouseNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={GreenhouseIcon} iconColor="" />
);
export const GreenhouseNode: NodeDefinition = {
    type: 'automation-greenhouse', label: 'Greenhouse',
    description: 'Greenhouse Harvest v3 recruiting automation',
    category: 'hr-recruiting',
    Icon: GreenhouseIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: GreenhouseNodeComponent,
};
