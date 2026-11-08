import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { forwardRef, type ImgHTMLAttributes } from 'react';

/** Original official mark; retain geometry and the canvas-supplied filter. */
export const AmplienceIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/amplience.svg" alt="" aria-hidden="true"
            className={className} style={{ ...style, objectFit: 'contain' }} />
    ),
);
AmplienceIcon.displayName = 'AmplienceIcon';



const AmplienceNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={AmplienceIcon as any} iconColor="" />
);
export const AmplienceNode: NodeDefinition = {
    type: 'automation-amplience',
    label: 'Amplience',
    description: 'Bound Content Management catalog and content metadata reads',
    category: 'content-research',
    Icon: AmplienceIcon as any,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(AmplienceNodeComponent),
};
