import type { CSSProperties as BrandCSSProperties } from 'react';
// Native Krisp meeting-service operations use the exact official K logomark.
import { memo, type ImgHTMLAttributes } from 'react';
import { type NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { type NodeDefinition } from '~/components/workflow/nodes/types';

// Sourced brand artwork: https://krisp.ai
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/krisp-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const KrispIcon = ({ style, ...props }: ImgHTMLAttributes<HTMLImageElement>) => (
    <img {...props} src="/icons/krisp.svg" alt="Krisp"
        style={{ objectFit: 'contain', background: '#fff', borderRadius: 6, padding: 5, ...style }} />
);

const KrispNodeComponent = (props: NodeProps) =>
    <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />;

export const KrispNode: NodeDefinition = {
    type: 'automation-krisp',
    label: 'Krisp',
    description: 'Read processed meetings, existing notes, transcripts and action items',
    category: 'meetings',
    Icon: PreferredBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 60 },
    component: memo(KrispNodeComponent),
};
