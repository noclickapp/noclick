// BigMailer is discovered from this definition alongside its generated schema.
// The icon is the official vendor logo, reviewed in its provenance sidecar.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const BigmailerIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/bigmailer.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
BigmailerIcon.displayName = 'BigmailerIcon';

export const BigmailerNode: NodeDefinition = {
    type: 'automation-bigmailer',
    label: 'BigMailer',
    description: 'Manage email contacts, lists and campaigns; send transactional emails',
    category: 'marketing',
    Icon: BigmailerIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BigmailerIcon} iconColor="" />),
};
