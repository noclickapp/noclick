import { forwardRef, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const JWPlayerIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/jwplayer.png" alt="" className={className}
            style={{ objectFit: 'contain', ...style }} {...props} />
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
