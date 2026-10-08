// ilert exposes protected actor and incident/status resource metadata reads.
// The original official white wordmark is contained on a dark background.
import { type ImgHTMLAttributes } from 'react';
import { type NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { type NodeDefinition } from './types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://ilert.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/ilert-brand-vector.svg" alt="" aria-hidden="true" className={(className || '') + ' [--brand-invert:0] dark:[--brand-invert:1]'}
        style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
);

export const IlertIcon = ({ style, ...props }: ImgHTMLAttributes<HTMLImageElement>) => (
    <img {...props} src="/icons/ilert.svg" alt="ilert"
        style={{ objectFit: 'contain', background: '#162c50', borderRadius: 8, padding: 8, ...style }} />
);
const IlertNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const IlertNode: NodeDefinition = {
    type: 'automation-ilert', label: 'ilert',
    description: 'Read current-user, team, service, incident and status-page metadata',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: IlertNodeComponent,
};
