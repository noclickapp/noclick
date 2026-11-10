import { forwardRef, type ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Unmodified official full-color mark; preserve supplied canvas filters and aspect ratio.
export const PulumiIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/pulumi.svg" alt="" aria-hidden="true"
            style={{ ...style, objectFit: 'contain' }} />
    ),
);
PulumiIcon.displayName = 'PulumiIcon';

const PulumiNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={PulumiIcon} iconColor="" />
);
export const PulumiNode: NodeDefinition = {
    type: 'automation-pulumi', category: 'cloud-hosting', label: 'Pulumi Cloud',
    description: 'Protected stack metadata, resource counts and downstream references without state, config or deployment control',
    keywords: ['Pulumi Cloud', 'stack metadata', 'resource counts', 'downstream references'],
    Icon: PulumiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: PulumiNodeComponent,
};
