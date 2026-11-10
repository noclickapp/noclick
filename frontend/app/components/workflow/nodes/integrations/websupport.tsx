// Websupport exposes signed, service-bound DNS metadata reads.
// The original vendor wordmark is displayed without changing its SVG bytes.
import { type ImgHTMLAttributes } from 'react';
import { type NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { type NodeDefinition } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://www.websupport.sk/
import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

// Sourced brand artwork: https://www.websupport.sk/
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/websupport-preferred-brand.svg" dark="/icons/websupport-preferred-brand-dark.svg" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const WebsupportIcon = ({ style, ...props }: ImgHTMLAttributes<HTMLImageElement>) => (
    <img {...props} src="/icons/websupport.svg" alt="Websupport" style={{ objectFit: 'contain', ...style }} />
);
const WebsupportNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />;
export const WebsupportNode: NodeDefinition = {
    type: 'automation-websupport', category: 'cloud-hosting', label: 'Websupport DNS', description: 'Read signed service-bound DNS metadata',
    Icon: PreferredBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: WebsupportNodeComponent,
};
