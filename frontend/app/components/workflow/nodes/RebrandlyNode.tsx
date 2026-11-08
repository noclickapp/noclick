// Rebrandly exposes closed workspace/domain/link metadata reads in the native editor.
// The unchanged official PNG favicon is separate from generated operation forms.
import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';

const RebrandlyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/rebrandly.png" alt="" className={className} style={style} {...props} />
    ),
);
RebrandlyIcon.displayName = 'RebrandlyIcon';

export const RebrandlyNode: NodeDefinition = {
    type: 'automation-rebrandly',
    label: 'Rebrandly',
    description: 'Read scoped workspace, domain and link metadata',
    category: 'marketing',
    Icon: RebrandlyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={RebrandlyIcon} iconColor="" />
    )),
};
