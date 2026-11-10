// Bytescale exposes three scoped file/folder metadata reads in the native editor.
// The unchanged vendor wordmark is separate from generated operation forms.
import { memo, type SVGProps } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.bytescale.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/bytescale-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const BytescaleIcon = ({ className, style }: SVGProps<SVGSVGElement>) => (
    <img src="/icons/bytescale.svg" alt="Bytescale" className={className} style={style} />
);

export const BytescaleNode: NodeDefinition = {
    type: 'automation-bytescale',
    label: 'Bytescale',
    description: 'Read scoped folder contents and file metadata',
    category: 'databases-storage',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
    )),
};
