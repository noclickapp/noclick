import { type ImgHTMLAttributes } from 'react';
import { type NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { type NodeDefinition } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://adapty.io
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/adapty-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const AdaptyIcon = ({ style, ...props }: ImgHTMLAttributes<HTMLImageElement>) => (
    <img {...props} src="/icons/adapty.svg" alt="Adapty" style={{ objectFit: 'contain', ...style }} />
);
const AdaptyNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const AdaptyNode: NodeDefinition = {
    type: 'automation-adapty',
    label: 'Adapty',
    description: 'Manage app profiles and read or change profile access levels',
    category: 'finance-accounting',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 60 },
    component: AdaptyNodeComponent,
};
