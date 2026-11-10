// Svix manages application and event-type metadata and reads delivery status.
// Regional environment keys and dependent application selectors retain scope.
// Endpoint secrets, custom headers and payload content are omitted from output.
import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://www.svix.com/
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/svix-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const SvixIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/svix.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />,
);
SvixIcon.displayName = 'SvixIcon';

export const SvixNode: NodeDefinition = {
    type: 'automation-svix',
    label: 'Svix',
    description: 'Application and event-type metadata with scoped delivery status',
    category: 'developer-tools',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
