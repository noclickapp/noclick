import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const LogoDevIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/logo-dev.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
LogoDevIcon.displayName = 'LogoDevIcon';

export const LogoDevNode: NodeDefinition = {
    type: 'automation-logo-dev',
    label: 'Logo Dev',
    description: 'Look up brands and logos, search companies, manage subscriptions and webhook endpoints',
    category: 'media',
    keywords: ['logo.dev', 'brand enrichment', 'brandmark'],
    Icon: LogoDevIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LogoDevIcon} iconColor="" />),
};
