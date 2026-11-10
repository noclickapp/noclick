import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const LogoDevIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/logo-dev.svg" dark="/icons/logo-dev-dark.svg" className={className} style={style} {...props} ref={ref} />
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
