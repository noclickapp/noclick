// Agorapulse's discoverable workflow definition uses the publisher's icon.
// Its backend schema supplies the API key form, operations and scheduled triggers.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const AgorapulseIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => <img ref={ref} src="/icons/agorapulse.svg" alt="" style={{ ...style, objectFit: 'contain' }} {...props} />,
);
AgorapulseIcon.displayName = 'AgorapulseIcon';
export const AgorapulseNode: NodeDefinition = {
    type: 'automation-agorapulse',
    label: 'Agorapulse',
    description: 'Manage calendar notes, social inbox replies, listening and new item triggers',
    category: 'social-media',
    Icon: AgorapulseIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AgorapulseIcon} iconColor="" />),
};
