import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const HookdeckIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/hookdeck.svg" alt="" className={className} style={style} {...props} />
    ),
);
HookdeckIcon.displayName = 'HookdeckIcon';

const HookdeckNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={HookdeckIcon} iconColor="" />
);

export const HookdeckNode: NodeDefinition = {
    type: 'automation-hookdeck',
    label: 'Hookdeck',
    description: 'Manage webhook sources, destinations, connections, events, and issues',
    Icon: HookdeckIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(HookdeckNodeComponent),
};
