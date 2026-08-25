// Mailchimp Marketing API automation node definition.
// Provides workflow integration with Mailchimp for email marketing, audiences, campaigns, and e-commerce.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Create icon component from SVG file
const MailchimpIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/mailchimp.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
MailchimpIcon.displayName = 'MailchimpIcon';

const MailchimpNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={MailchimpIcon} iconColor="" />;
};

export const MailchimpNode: NodeDefinition = {
    type: 'automation-mailchimp',
    label: 'Mailchimp',
    description: 'Mailchimp automation',
    Icon: MailchimpIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(MailchimpNodeComponent),
};
