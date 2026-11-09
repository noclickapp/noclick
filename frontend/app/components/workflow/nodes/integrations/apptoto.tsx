// Apptoto's own wordmark identifies its appointment automation node.
// The adjacent provenance sidecar records the publisher and exact asset bytes.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const ApptotoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/apptoto.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ApptotoIcon.displayName = 'ApptotoIcon';

export const ApptotoNode: NodeDefinition = {
    type: 'automation-apptoto',
    label: 'Apptoto',
    description: 'Manage appointments, contacts, booking pages and conversations',
    category: 'bookings',
    keywords: ['appointments', 'reminders', 'scheduling', 'SMS'],
    Icon: ApptotoIcon,
    iconColor: '',
    dimensions: { width: 110, height: 80, iconSize: 80 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ApptotoIcon} iconColor="" />),
};
