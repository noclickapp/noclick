// ngrok automation node for endpoints, tunnels, domains and account resources.
// It displays the official dark ngrok n mark on a light tile for both themes.

import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const NgrokIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <ThemedBrandImg light="/icons/ngrok.svg" dark="/icons/ngrok-dark.svg" className={className} style={style} {...props} ref={ref} />
));
NgrokIcon.displayName = 'NgrokIcon';

const NgrokNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={NgrokIcon} iconColor="" />
);

export const NgrokNode: NodeDefinition = {
    type: 'automation-ngrok',
    category: 'developer-tools',
    label: 'ngrok',
    description:
        'Manage ngrok resources and trigger workflows when endpoints, tunnel sessions or domains are created',
    Icon: NgrokIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: NgrokNodeComponent,
};
