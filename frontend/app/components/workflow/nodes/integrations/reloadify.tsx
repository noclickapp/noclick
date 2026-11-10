// Reloadify's catalog and canvas definition. The icon is the provider's own
// published asset, with its source and hash recorded in the adjacent sidecar.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const ReloadifyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/reloadify.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ReloadifyIcon.displayName = 'ReloadifyIcon';

export const ReloadifyNode: NodeDefinition = {
    type: 'automation-reloadify',
    label: 'Reloadify',
    description: 'Automate customer profiles, orders, carts and retention marketing',
    category: 'marketing',
    Icon: ReloadifyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ReloadifyIcon} iconColor="" />),
};
