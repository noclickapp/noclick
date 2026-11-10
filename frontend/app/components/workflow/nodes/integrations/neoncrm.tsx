// Native Neon CRM node for organization, constituent and activity workflows.
// Keeps the official Developer Center vector unchanged and adds service aliases
// used by both the canvas and agent wiring palettes.
import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://neonone.com/solutions/neon-crm-overview/
import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/neoncrm-brand.svg" dark="/icons/neoncrm-brand-dark.svg" className={className} style={style} />
);

export const NeonCRMIcon = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/neoncrm.svg" alt="" className={className}
            style={{ ...style, objectFit: 'contain' }} />
    ),
);
NeonCRMIcon.displayName = 'NeonCRMIcon';

export const NeonCRMNode: NodeDefinition = {
    type: 'automation-neoncrm',
    label: 'Neon CRM',
    description: 'Neon CRM accounts, company contacts, legacy events and activities',
    category: 'nonprofit',
    keywords: ['neon', 'neoncrm', 'constituent', 'nonprofit', 'activity', 'report'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
