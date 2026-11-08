// Dialpad's API node for business calls, SMS, contacts, and user management.
// Uses the unmodified official dark app icon linked from Dialpad's brand downloads.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DialpadIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/dialpad.svg" alt="" className={className}
            style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
DialpadIcon.displayName = 'DialpadIcon';

export const DialpadNode: NodeDefinition = {
    type: 'automation-dialpad',
    label: 'Dialpad',
    description: 'Manage calls, send SMS, sync contacts, and update users in Dialpad',
    keywords: ['phone', 'calling', 'sms', 'text message', 'contacts', 'users', 'dnd'],
    Icon: DialpadIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DialpadIcon} iconColor="" />),
};
