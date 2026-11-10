// Bluefox Email exposes project-scoped email and audience automation.
// This definition makes its generated configuration available in the workflow and integration catalogs.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const BluefoxEmailIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/bluefox-email.png" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/bluefox-email-dark.png" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
    ),
);
BluefoxEmailIcon.displayName = 'BluefoxEmailIcon';

export const BluefoxEmailNode: NodeDefinition = {
    type: 'automation-bluefox-email',
    label: 'Bluefox Email',
    description: 'Manage contacts and subscriber lists, inspect campaigns, and send transactional or triggered email',
    category: 'marketing',
    keywords: ['bluefox', 'bluefox.email', 'email marketing', 'newsletter', 'subscribers'],
    Icon: BluefoxEmailIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BluefoxEmailIcon} iconColor="" />),
};
