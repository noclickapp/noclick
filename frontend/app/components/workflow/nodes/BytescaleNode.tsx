// Bytescale exposes three scoped file/folder metadata reads in the native editor.
// The unchanged vendor wordmark is separate from generated operation forms.
import { memo, type SVGProps } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';


// Unmodified compact brand asset from https://www.bytescale.com/
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/bytescale-brand.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const BytescaleIcon = ({ className, style }: SVGProps<SVGSVGElement>) => (
    <img src="/icons/bytescale.svg" alt="Bytescale" className={className} style={style} />
);

export const BytescaleNode: NodeDefinition = {
    type: 'automation-bytescale',
    label: 'Bytescale',
    description: 'Read scoped folder contents and file metadata',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
    )),
};
