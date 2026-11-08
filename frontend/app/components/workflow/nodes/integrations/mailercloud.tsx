import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const MailercloudIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/mailercloud.png" alt="" className={className}
            style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
MailercloudIcon.displayName = 'MailercloudIcon';

export const MailercloudNode: NodeDefinition = {
    type: 'automation-mailercloud',
    label: 'Mailercloud',
    category: 'marketing',
    description: 'Manage contacts, lists and tags; read campaigns and engagement',
    keywords: ['email marketing', 'newsletter', 'subscriber', 'mailercloud'],
    Icon: MailercloudIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MailercloudIcon} iconColor="" />),
};
