import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const EasyEmailVerificationIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/easy-email-verification.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
EasyEmailVerificationIcon.displayName = 'EasyEmailVerificationIcon';

export const EasyEmailVerificationNode: NodeDefinition = {
    type: 'automation-easy-email-verification',
    label: 'Easy Email Verification',
    description: 'Verify emails, manage bulk verification jobs and check credits',
    category: 'marketing',
    keywords: ['email validation', 'email verification', 'deliverability', 'bulk email'],
    Icon: EasyEmailVerificationIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EasyEmailVerificationIcon} iconColor="" />),
};
