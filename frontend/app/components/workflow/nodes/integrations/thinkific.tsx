// Thinkific workflow node for learner management, enrollment, and commerce automation.
// Registers the canvas component with the official Thinkific icon and searchable operation keywords.
import { memo, forwardRef } from 'react';
import type { ImgHTMLAttributes } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Unmodified Thinkific mark from its official Partner Marketing Kit logo pack.
const ThinkificIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <ThemedBrandImg {...props} light="/icons/thinkific.svg" dark="/icons/thinkific-dark.svg" className={className} style={style} ref={ref} />
));
ThinkificIcon.displayName = 'ThinkificIcon';

export const ThinkificNode: NodeDefinition = {
    type: 'automation-thinkific',
    category: 'courses',
    label: 'Thinkific',
    description:
        'Create and update students, enroll in courses and bundles, sync orders and purchases, and trigger workflows from student activity',
    keywords: [
        'students',
        'learners',
        'courses',
        'enrollments',
        'bundles',
        'orders',
        'purchases',
        'learning management',
        'webhooks',
        'course completion',
        'triggers',
    ],
    Icon: ThinkificIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={ThinkificIcon} iconColor="" />
    )),
};
