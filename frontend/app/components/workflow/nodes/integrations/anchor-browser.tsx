import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const AnchorBrowserIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/anchor-browser.svg" dark="/icons/anchor-browser-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
AnchorBrowserIcon.displayName = 'AnchorBrowserIcon';

export const AnchorBrowserNode: NodeDefinition = {
    type: 'automation-anchor-browser',
    label: 'Anchor Browser',
    description: 'Automate cloud browser sessions, web tasks, profiles and browser actions',
    category: 'developer-tools',
    keywords: ['anchor', 'browser automation', 'web tasks', 'cloud browser'],
    Icon: AnchorBrowserIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AnchorBrowserIcon} iconColor="" />),
};
