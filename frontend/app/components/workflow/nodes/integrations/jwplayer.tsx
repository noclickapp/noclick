import { forwardRef, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const JWPlayerIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg {...props} light="/icons/jwplayer.svg" dark="/icons/jwplayer-dark.svg" ref={ref} className={className} style={{ objectFit: 'contain', ...style }} />
    )
);
JWPlayerIcon.displayName = 'JWPlayerIcon';

export const JWPlayerNode: NodeDefinition = {
    type: 'automation-jwplayer',
    label: 'JWX (JW Player)',
    description: 'Read property media, playlist and content-type metadata',
    category: 'media',
    keywords: ['jwplayer', 'jwp', 'jwx', 'video', 'media', 'playlist', 'dam'],
    Icon: JWPlayerIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JWPlayerIcon} iconColor="" />),
};
