// Websupport exposes signed, service-bound DNS metadata reads.
// The original vendor wordmark is displayed without changing its SVG bytes.
import { type ImgHTMLAttributes } from 'react';
import { type NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { type NodeDefinition } from './types';


// Unmodified compact brand asset from https://www.websupport.sk/
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/websupport-brand.svg" alt="" aria-hidden="true" className={(className || '') + ' [--brand-invert:0] dark:[--brand-invert:1]'}
        style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
);

export const WebsupportIcon = ({ style, ...props }: ImgHTMLAttributes<HTMLImageElement>) => (
    <img {...props} src="/icons/websupport.svg" alt="Websupport" style={{ objectFit: 'contain', ...style }} />
);
const WebsupportNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const WebsupportNode: NodeDefinition = {
    type: 'automation-websupport', label: 'Websupport DNS', description: 'Read signed service-bound DNS metadata',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: WebsupportNodeComponent,
};
