import type { CSSProperties as BrandCSSProperties } from 'react';
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

// Sourced brand artwork: https://www.granola.ai
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/granola-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const GranolaIcon: SvgIconComponent = forwardRef<
    HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>
>((props, ref) => (
    <ThemedBrandImg ref={ref} light="/icons/granola.svg" dark="/icons/granola-dark.svg" {...props} />
));
GranolaIcon.displayName = 'GranolaIcon';

const GranolaNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />
);

export const GranolaNode: NodeDefinition = {
    type: 'automation-granola', category: 'meetings', label: 'Granola',
    description: 'Meeting notes, transcripts, folders and workspace administration', Icon: PreferredBrandIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(GranolaNodeComponent),
};
