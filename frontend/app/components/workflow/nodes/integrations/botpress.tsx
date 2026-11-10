// Botpress administration and table data use a workspace/bot-bound existing PAT.
// The publisher's exact SVG is displayed without rebuilding the vendor artwork.
import { forwardRef, memo } from 'react';
import type { ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://botpress.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/botpress-brand-vector.svg" alt="" aria-hidden="true" className={(className || '') + ' [--brand-invert:0] dark:[--brand-invert:1]'}
        style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
);

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
    category: 'ai',
    keywords: ['administration', 'workspace', 'bots', 'tables', 'rows', 'files'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
