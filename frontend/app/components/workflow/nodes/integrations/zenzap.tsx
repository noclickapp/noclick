// Zenzap's definition makes its chat and task automation discoverable.
// The icon is the provider's published brand asset, with provenance beside it.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const ZenzapIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/zenzap.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ZenzapIcon.displayName = 'ZenzapIcon';

export const ZenzapNode: NodeDefinition = {
    type: 'automation-zenzap',
    label: 'Zenzap',
    description: 'Automate team messages, topics, members and tasks',
    category: 'communication',
    keywords: ['chat', 'team', 'message', 'task'],
    Icon: ZenzapIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZenzapIcon} iconColor="" />),
};
