// Mailgun email automation node definition.
// Provides workflow integration with the Mailgun REST API (messages, domains,
// mailing lists, templates, routes, suppressions, validation) plus a webhook
// trigger for delivery events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const MailgunIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/mailgun.svg" alt="" className={className} style={style} {...props} />
));
MailgunIcon.displayName = 'MailgunIcon';

const MailgunNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={MailgunIcon} iconColor="" />;
};

export const MailgunNode: NodeDefinition = {
    type: 'automation-mailgun',
    label: 'Mailgun',
    description: 'Mailgun email automation',
    Icon: MailgunIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(MailgunNodeComponent),
};
