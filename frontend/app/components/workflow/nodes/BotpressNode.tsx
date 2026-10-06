// Botpress administration and table data use a workspace/bot-bound existing PAT.
// The publisher's exact SVG is displayed without rebuilding the vendor artwork.
import { forwardRef, memo } from 'react';
import type { ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';

export const BotpressIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/botpress.svg" alt="" className={className} style={style} {...props} />
    ),
);
BotpressIcon.displayName = 'BotpressIcon';

export const BotpressNode: NodeDefinition = {
    type: 'automation-botpress',
    label: 'Botpress',
    description: 'Botpress workspace, bot, table data and file metadata workflows',
    keywords: ['administration', 'workspace', 'bots', 'tables', 'rows', 'files'],
    Icon: BotpressIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BotpressIcon} iconColor="" />),
};
