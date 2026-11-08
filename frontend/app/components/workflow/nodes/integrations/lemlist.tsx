import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.lemlist.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/lemlist-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };
const LemlistIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/lemlist.svg" alt="" className={className} style={style} {...props} />
);
LemlistIcon.displayName = 'LemlistIcon';
const LemlistNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;

export const LemlistNode: NodeDefinition = {
    type: 'automation-lemlist',
    category: 'crm-sales',
    label: 'Lemlist',
    description: 'Lemlist sales outreach automation', Icon: OfficialBrandIcon,
    iconColor: '', dimensions: DIMENSIONS, component: memo(LemlistNodeComponent),
};
