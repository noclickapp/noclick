// Adobe Campaign exposes explicit Standard and enabled v8 FDA REST metadata.
// Typed native credentials hold supplied OAuth access and the exact tenant route.
// The official Adobe mark is displayed honestly without implying another product icon.
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.adobe.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/adobe-campaign-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const AdobeCampaignNode: NodeDefinition = {
    type: 'automation-adobe-campaign',
    label: 'Adobe Campaign',
    description: 'Campaign profiles, services and custom-resource metadata',
    category: 'marketing',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
