// Audiobookshelf exposes closed library/author metadata reads in the native editor.
// The unchanged official PNG icon is separate from generated operation forms.
import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const AudiobookshelfIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/audiobookshelf.png" alt="" className={className} style={{ ...style, objectFit: "contain" }} {...props} />
    ),
);
AudiobookshelfIcon.displayName = 'AudiobookshelfIcon';

export const AudiobookshelfNode: NodeDefinition = {
    type: 'automation-audiobookshelf',
    label: 'Audiobookshelf',
    description: 'Read scoped library and author metadata',
    Icon: AudiobookshelfIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={AudiobookshelfIcon} iconColor="" />
    )),
};
