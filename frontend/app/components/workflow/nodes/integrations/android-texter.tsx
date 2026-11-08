import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const AndroidTexterIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/android-texter.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
AndroidTexterIcon.displayName = 'AndroidTexterIcon';

export const AndroidTexterNode: NodeDefinition = {
    type: 'automation-android-texter',
    label: 'Android Texter',
    description: 'Send SMS and MMS through Android phones; manage messages, contacts, quick replies, spam and webhooks',
    category: 'communication',
    keywords: ['sms', 'mms', 'text message', 'android', 'phone', 'broadcast'],
    Icon: AndroidTexterIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AndroidTexterIcon} iconColor="" />),
};
