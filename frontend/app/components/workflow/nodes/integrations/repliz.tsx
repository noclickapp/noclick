import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
const ReplizIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <>
        <img ref={ref} src="/icons/repliz.svg" alt="" className={`${className || ''} dark:hidden`} style={style} {...props} />
        <img src="/icons/repliz-dark.svg" alt="" className={`${className || ''} hidden dark:block`} style={style} {...props} />
    </>,
);
ReplizIcon.displayName = 'ReplizIcon';
export const ReplizNode: NodeDefinition = {
    type: 'automation-repliz', label: 'Repliz', description: 'Manage social comments, contacts, messages and scheduled posts',
    category: 'social-media', Icon: ReplizIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ReplizIcon} iconColor="" />),
};
