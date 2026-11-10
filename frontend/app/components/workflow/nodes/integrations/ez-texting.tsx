// EZ Texting exposes the provider's contact and messaging API in workflows.
// Its schema and credential metadata are generated from the Python node.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const EZTextingIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/ez-texting.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/ez-texting-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
    ),
);
EZTextingIcon.displayName = 'EZTextingIcon';

export const EZTextingNode: NodeDefinition = {
    type: 'automation-ez-texting',
    label: 'EZ Texting',
    description: 'Send and schedule texts, manage contacts, groups and templates, and read message reports.',
    category: 'communication',
    keywords: ['sms', 'mms', 'text messages', 'eztexting'],
    Icon: EZTextingIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EZTextingIcon} iconColor="" />),
};
