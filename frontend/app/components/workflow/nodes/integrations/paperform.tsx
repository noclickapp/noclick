import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const PaperformIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/paperform.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
PaperformIcon.displayName = 'PaperformIcon';

export const PaperformNode: NodeDefinition = {
    type: 'automation-paperform',
    label: 'Paperform',
    description: 'Manage forms, submissions, products, coupons and webhooks',
    keywords: ['forms', 'survey', 'submission', 'partial submission', 'coupon', 'product', 'webhook'],
    Icon: PaperformIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PaperformIcon} iconColor="" />),
};
