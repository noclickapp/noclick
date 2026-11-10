// Talkable’s self-registering canvas and catalog definition. The shared discovery loader finds this provider without registry edits.
import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const TalkableIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/talkable.svg" alt="" className={className} style={style} {...props} />
    ),
);
TalkableIcon.displayName = 'TalkableIcon';

export const TalkableNode: NodeDefinition = {
    type: 'automation-talkable',
    label: 'Talkable',
    category: 'marketing',
    description: 'Site-scoped referral reports and person metadata',
    Icon: TalkableIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={TalkableIcon} iconColor="" />,
};
