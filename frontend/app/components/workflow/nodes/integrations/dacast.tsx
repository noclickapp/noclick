// Dacast reads approved channel, video, folder and playlist metadata.
// This native editor definition displays the unaltered official documentation icon.
import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
const DacastIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/dacast.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />,
);
DacastIcon.displayName = 'DacastIcon';
export const DacastNode: NodeDefinition = {
    type: 'automation-dacast', label: 'Dacast', category: 'media',
    description: 'Read scoped channel, video, folder and playlist metadata',
    keywords: ['dacast', 'video', 'vod', 'channels', 'folders', 'playlists'],
    Icon: DacastIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DacastIcon} iconColor="" />),
};
