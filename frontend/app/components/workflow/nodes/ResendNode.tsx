// Resend transactional email node definition.
// Provides workflow integration for sending, tracking, and managing transactional
// emails via the Resend API, plus a webhook trigger for delivery events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const DIMENSIONS = { width: 90, height: 90, iconSize: 42 };

// Official Resend brand icon (white variant) from cdn.resend.com/brand.
const ResendIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>((props, ref) => (
    <ThemedBrandImg ref={ref} light="/icons/resend-light.svg" dark="/icons/resend.svg" {...props} />
));
ResendIcon.displayName = 'ResendIcon';

const ResendNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ResendIcon} iconColor="" />;
};

export const ResendNode: NodeDefinition = {
    type: 'automation-resend',
    label: 'Resend',
    description: 'Transactional email',
    Icon: ResendIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ResendNodeComponent),
};
