import type { CSSProperties as BrandCSSProperties } from 'react';
// PredictLeads reads company intelligence through its native v3 header-key API.
// This definition registers the editor node and its unchanged official icon.
import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';

// Sourced brand artwork: https://logos.composio.dev/api/predict_leads
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/predictleads-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const PredictLeadsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/predictleads.svg" alt="" className={className} style={style} {...props} />,
);
PredictLeadsIcon.displayName = 'PredictLeadsIcon';

export const PredictLeadsNode: NodeDefinition = {
    type: 'automation-predictleads', category: 'crm-sales', label: 'PredictLeads',
    description: 'Read subscription, company, job, news and technology signals with explicit credit limits',
    keywords: ['PredictLeads', 'company', 'job openings', 'news events', 'technologies', 'subscription'],
    Icon: PreferredBrandIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />),
};
