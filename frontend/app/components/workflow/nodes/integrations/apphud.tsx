// Apphud catalog and canvas definition. Discovered without a shared registry entry.
import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://apphud.com
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/apphud-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const ApphudIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>((props, ref) => (
    <img ref={ref} src="/icons/apphud.svg" alt="" {...props} />
));
ApphudIcon.displayName = 'ApphudIcon';
const ApphudNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;

export const ApphudNode: NodeDefinition = {
    type: 'automation-apphud', category: 'finance-accounting', label: 'Apphud',
    description: 'Read protected application charts and query subscription analytics',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(ApphudNodeComponent),
};
