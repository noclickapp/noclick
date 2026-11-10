import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const TelzioIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/telzio.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
TelzioIcon.displayName = 'TelzioIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const TelzioNode: NodeDefinition = {
    type: 'automation-telzio',
    label: 'Telzio',
    description: 'SMS, calls, contacts, users, queues and voicemail',
    category: 'communication',
    Icon: TelzioIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TelzioIcon} iconColor="" />),
};
