import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://neon.com
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/neon-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const NeonIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/neon.svg" alt="" className={className} style={style} {...props} />
    ),
);
NeonIcon.displayName = 'NeonIcon';

export const NeonNode: NodeDefinition = {
    type: 'automation-neon',
    label: 'Neon',
    description: 'Manage Neon projects, branches, databases, computes, and backend services',
    category: 'databases-storage',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
