import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const PaperformIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/paperform.svg" dark="/icons/paperform-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
PaperformIcon.displayName = 'PaperformIcon';

export const PaperformNode: NodeDefinition = {
    type: 'automation-paperform',
    label: 'Paperform',
    description: 'Manage forms, submissions, products, coupons and webhooks',
    category: 'forms',
    keywords: ['forms', 'survey', 'submission', 'partial submission', 'coupon', 'product', 'webhook'],
    Icon: PaperformIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PaperformIcon} iconColor="" />),
};
