// Tally REST API workflow node for forms, submissions, analytics, and webhooks.

import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const TallyIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/tally.svg"
        alt=""
        className={`${className || ''} rounded-xl bg-white p-1.5`}
        style={style}
        {...props}
    />
));
TallyIcon.displayName = 'TallyIcon';

const TallyNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={TallyIcon} iconColor="" />;
};

export const TallyNode: NodeDefinition = {
    type: 'automation-tally',
    category: 'forms',
    label: 'Tally',
    description:
        'Create forms, manage submissions, inspect analytics, and configure webhooks',
    Icon: TallyIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(TallyNodeComponent),
    keywords: [
        'form',
        'survey',
        'responses',
        'submission',
        'webhook',
        'analytics',
    ],
};
