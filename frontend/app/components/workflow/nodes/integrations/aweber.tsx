// AWeber automation node for subscriber, list, and email marketing actions.
// The icon comes from AWeber's published brand symbol and is shared with its credential picker.

import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const AWeberIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/aweber.svg" alt="" className={className} style={style} {...props} />
));
AWeberIcon.displayName = 'AWeberIcon';

const AWeberNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={AWeberIcon} iconColor="" />
);

export const AWeberNode: NodeDefinition = {
    type: 'automation-aweber',
    label: 'AWeber',
    category: 'marketing',
    description: 'Manage AWeber subscribers, lists, broadcasts, and campaigns',
    Icon: AWeberIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: AWeberNodeComponent,
};
