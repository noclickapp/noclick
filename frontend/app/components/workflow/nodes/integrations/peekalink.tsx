import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const PeekalinkIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg {...props} ref={ref} light="/icons/peekalink.svg" dark="/icons/peekalink-dark.svg" className={className} style={style} />
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
