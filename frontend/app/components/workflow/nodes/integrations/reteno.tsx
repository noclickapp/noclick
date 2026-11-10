import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const RetenoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/reteno.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
RetenoIcon.displayName = 'RetenoIcon';

// Official website icon; provenance is recorded beside the asset.
export const RetenoNode: NodeDefinition = {
    type: 'automation-reteno',
    label: 'Reteno',
    description: 'Automate Reteno contacts, segments, email messages, events and subscriptions',
    category: 'marketing',
    Icon: RetenoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RetenoIcon} iconColor="" />),
};
