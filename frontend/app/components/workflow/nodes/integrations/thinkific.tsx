// Thinkific workflow node for learner management, enrollment, and commerce automation.
// Registers the canvas component with the official Thinkific icon and searchable operation keywords.
import { memo, forwardRef } from 'react';
import type { CSSProperties, ImgHTMLAttributes } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

// Unmodified Thinkific mark from its official Partner Marketing Kit logo pack.
const ThinkificIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <>
        <img
            ref={ref}
            src="/icons/thinkific.svg"
            alt=""
            aria-hidden="true"
            className={`${className ?? ''} dark:hidden`}
            style={
                {
                    ...style,
                    '--brand-invert': 0,
                    objectFit: 'contain',
                } as CSSProperties
            }
            {...props}
        />
        <img
            src="/icons/thinkific-dark.svg"
            alt=""
            aria-hidden="true"
            className={`${className ?? ''} hidden dark:block`}
            style={
                {
                    ...style,
                    '--brand-invert': 0,
                    objectFit: 'contain',
                } as CSSProperties
            }
            {...props}
        />
    </>
));
ThinkificIcon.displayName = 'ThinkificIcon';

export const ThinkificNode: NodeDefinition = {
    type: 'automation-thinkific',
    category: 'courses',
    label: 'Thinkific',
    description:
        'Create and update students, enroll in courses and bundles, and sync orders and purchases',
    keywords: [
        'students',
        'learners',
        'courses',
        'enrollments',
        'bundles',
        'orders',
        'purchases',
        'learning management',
    ],
    Icon: ThinkificIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={ThinkificIcon} iconColor="" />
    )),
};
