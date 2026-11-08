import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

// Exact official white wordmark; compose the existing canvas theme/shadow filter.

// Unmodified compact brand asset from https://www.mightynetworks.com/
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/mighty-networks-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const MightyNetworksIcon: SvgIconComponent = forwardRef<
    HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img {...props} ref={ref} src="/icons/mighty-networks.svg" alt=""
        className={['brand-mono', className].filter(Boolean).join(' ')}
        style={{ ...style, objectFit: 'contain', filter: style?.filter ?? 'invert(var(--brand-invert, 1))' }} />
));
MightyNetworksIcon.displayName = 'MightyNetworksIcon';
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const MightyNetworksNode: NodeDefinition = {
    type: 'automation-mighty-networks', category: 'courses', label: 'Mighty Networks',
    description: 'Network, Space, collection, tag and owned draft post workflows',
    keywords: ['Mighty API', 'community', 'spaces', 'drafts', 'Mighty Networks'],
    Icon: OfficialBrandIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 }, component: Component,
};
