/** Native Metricool brand analytics and unpublished draft node.
 * Uses the shared credential/config form and an unchanged official Metricool icon. */
import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://metricool.com/newsroom/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/metricool-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const MetricoolIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/metricool.png" alt="" className={className} style={style} {...props} />,
);
MetricoolIcon.displayName = 'MetricoolIcon';

export const MetricoolNode: NodeDefinition = {
    type: 'automation-metricool',
    label: 'Metricool',
    description: 'Accessible brand analytics, scheduler metadata and unpublished Facebook text drafts',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
