import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const AnchorBrowserIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/anchor-browser.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
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
