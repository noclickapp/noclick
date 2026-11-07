// Koyeb native cloud metadata node and exact vendor icon.
// Added to expose organization-bound inventory and empty-app management in workflows.
import { type ImgHTMLAttributes } from 'react';
import { type NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { type NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.koyeb.com

// Sourced brand artwork: https://www.koyeb.com
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/koyeb-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const KoyebIcon = ({ style, ...props }: ImgHTMLAttributes<HTMLImageElement>) => (
    <img {...props} src="/icons/koyeb.svg" alt="Koyeb" style={{ objectFit: 'contain', ...style }} />
);
const KoyebNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />;
export const KoyebNode: NodeDefinition = {
    type: 'automation-koyeb',
    label: 'Koyeb',
    description: 'Read cloud inventory and status; manage empty app metadata',
    Icon: PreferredBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 60 },
    component: KoyebNodeComponent,
};
