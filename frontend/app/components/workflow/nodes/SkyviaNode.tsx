// Native Skyvia workspace and management metadata node.
// Uses the current shared editor shell and exact official vendor SVG.
import { forwardRef, memo } from 'react';
import type { ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://skyvia.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/skyvia-brand-vector.svg" alt="" aria-hidden="true" className={(className || '') + ' [--brand-invert:0] dark:[--brand-invert:1]'}
        style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
);

const SkyviaIcon: SvgIconComponent = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    (props, ref) => <img {...props} ref={ref} src="/icons/skyvia.svg" alt="" />
);
SkyviaIcon.displayName = 'SkyviaIcon';
export const SkyviaNode: NodeDefinition = {
    type: 'automation-skyvia', label: 'Skyvia',
    description: 'Read workspace, connection, integration, backup and automation metadata',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
