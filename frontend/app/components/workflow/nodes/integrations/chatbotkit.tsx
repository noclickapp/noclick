import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const ChatBotKitIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <>
        <img
            ref={ref}
            src="/icons/chatbotkit.svg"
            alt=""
            className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' }}
            {...props}
        />
        <img
            src="/icons/chatbotkit-dark.svg"
            alt=""
            className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' }}
            {...props}
        />
    </>
));
ChatBotKitIcon.displayName = 'ChatBotKitIcon';

// Official publisher icon; provenance is recorded beside the image.
export const ChatBotKitNode: NodeDefinition = {
    type: 'automation-chatbotkit',
    label: 'ChatBotKit',
    description:
        'Automate AI bots, conversations, knowledge datasets and contacts',
    category: 'ai',
    Icon: ChatBotKitIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={ChatBotKitIcon} iconColor="" />
    )),
};
