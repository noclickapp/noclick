// Native app-bound user/conversation/message workflows; tokens stay server-side.
import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';
const TalkJSIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/talkjs.svg" alt="" className={className} style={{ objectFit: 'contain', ...style }} {...props} />,
);
TalkJSIcon.displayName = 'TalkJSIcon';
const TalkJSNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={TalkJSIcon} iconColor="" />;
export const TalkJSNode: NodeDefinition = {
  type: 'automation-talkjs', label: 'TalkJS', description: 'App user metadata, scoped conversations and explicit message workflows',
  Icon: TalkJSIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: TalkJSNodeComponent,
};
