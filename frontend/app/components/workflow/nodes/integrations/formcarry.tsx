// Formcarry's catalog and canvas definition uses the publisher's icon.
// The backend schema supplies operation configuration and credential fields.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const FormcarryIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/formcarry.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
FormcarryIcon.displayName = 'FormcarryIcon';
export const FormcarryNode: NodeDefinition = {
    type: 'automation-formcarry', category: 'forms', label: 'Formcarry',
    description: 'Manage forms, submissions, notifications and webhooks',
    keywords: ['forms', 'submissions', 'spam', 'webhooks'],
    Icon: FormcarryIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FormcarryIcon} iconColor="" />),
};
