import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const BlooioIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/blooio.svg" dark="/icons/blooio-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
BlooioIcon.displayName = 'BlooioIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const BlooioNode: NodeDefinition = {
    type: 'automation-blooio',
    label: 'Blooio',
    category: 'communication',
    description: 'Send messages and manage contacts, chats, channels, and events',
    Icon: BlooioIcon,
    keywords: ['iMessage', 'SMS', 'RCS', 'WhatsApp', 'messaging'],
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BlooioIcon} iconColor="" />),
};
