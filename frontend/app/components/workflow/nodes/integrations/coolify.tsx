import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const CoolifyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/coolify.svg" alt="" className={className} style={style} {...props} />,
);
CoolifyIcon.displayName = 'CoolifyIcon';
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={CoolifyIcon} iconColor="" />;
export const CoolifyNode: NodeDefinition = {
    type: 'automation-coolify', category: 'cloud-hosting', label: 'Coolify',
    description: 'Coolify team, project, environment and deployment metadata',
    Icon: CoolifyIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: Component,
};
