// ngrok automation node for endpoints, tunnels, domains and account resources.
// It displays the official dark ngrok n mark on a light tile for both themes.

import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const NgrokIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <>
        <img
            ref={ref}
            src="/icons/ngrok.svg"
            alt=""
            className={`${className || ''} dark:hidden`}
            style={style}
            {...props}
        />
        <img
            src="/icons/ngrok-dark.svg"
            alt=""
            className={`${className || ''} hidden dark:block`}
            style={style}
            {...props}
        />
    </>
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
        'Manage ngrok endpoints, tunnels, domains, vaults and account resources',
    Icon: NgrokIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: NgrokNodeComponent,
};
