import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const PeekalinkIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img {...props} ref={ref} src="/icons/peekalink.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} />
            <img {...props} src="/icons/peekalink-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} />
        </>
    ),
);
PeekalinkIcon.displayName = 'PeekalinkIcon';

export const PeekalinkNode: NodeDefinition = {
    type: 'automation-peekalink',
    label: 'Peekalink',
    description: 'Link previews, URL metadata, images and social media details',
    keywords: ['unfurl', 'link preview', 'URL metadata', 'YouTube', 'Peekalink'],
    category: 'content-research',
    Icon: PeekalinkIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PeekalinkIcon} iconColor="" />),
};
