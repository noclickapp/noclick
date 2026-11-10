import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const StackExchangeIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg {...props} light="/icons/stack-exchange.svg" className={className} style={style} ref={ref} />
    ),
);
StackExchangeIcon.displayName = 'StackExchangeIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const StackExchangeNode: NodeDefinition = {
    type: 'automation-stack-exchange',
    label: 'Stack Exchange',
    description: 'Read questions, answers, users and tags, and create, edit or delete comments',
    category: 'developer-tools',
    Icon: StackExchangeIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={StackExchangeIcon} iconColor="" />),
};
