// SignalWire project communication and resource node.
// The shared editor renders typed operations and a project-scoped connection;
// this definition adds the actual provider to the palette and canvas.
import { forwardRef, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const SignalWireIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/signalwire.svg" alt="" className={className} style={style} {...props} />
);
SignalWireIcon.displayName = 'SignalWireIcon';

const SignalWireNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={SignalWireIcon} iconColor="" />;

export const SignalWireNode: NodeDefinition = {
    type: 'automation-signalwire',
    label: 'SignalWire',
    description: 'Project metadata, message and call logs, SMS and owned numbers',
    Icon: SignalWireIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(SignalWireNodeComponent),
};
