import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const VendschatIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/vendschat.svg" alt="" {...props} className={className} style={style} />
    ),
);
VendschatIcon.displayName = 'VendschatIcon';

export const VendschatNode: NodeDefinition = {
    type: 'automation-vendschat',
    label: 'Vendschat',
    description: 'Send messages, manage contacts and labels, and receive WhatsApp messages',
    category: 'communication',
    Icon: VendschatIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VendschatIcon} iconColor="" />),
};
