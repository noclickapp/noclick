import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const E2BIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/e2b.svg" dark="/icons/e2b-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
E2BIcon.displayName = 'E2BIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const E2BNode: NodeDefinition = {
    type: 'automation-e2b',
    label: 'E2B',
    description: 'Manage sandboxes, templates, snapshots, events and webhooks',
    category: 'developer-tools',
    Icon: E2BIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={E2BIcon} iconColor="" />),
};
