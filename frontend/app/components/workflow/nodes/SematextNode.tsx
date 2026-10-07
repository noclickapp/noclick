// Sematext Cloud reads approved app and alert-rule metadata.
// This native editor definition displays the original official documentation logo.
import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';
const SematextIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/sematext.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />,
);
SematextIcon.displayName = 'SematextIcon';
export const SematextNode: NodeDefinition = {
    type: 'automation-sematext', label: 'Sematext Cloud',
    description: 'Read scoped app and alert-rule metadata',
    keywords: ['sematext', 'observability', 'apps', 'alert rules'],
    Icon: SematextIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SematextIcon} iconColor="" />),
};
