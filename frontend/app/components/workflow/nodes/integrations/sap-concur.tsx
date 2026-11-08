// Native SAP Concur canvas entry uses the standard automation form.
// The icon is unchanged vendor SVG; schema and metadata are generated separately.
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://concur.com
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/sap-concur-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const SAPConcurNode: NodeDefinition = {
    type: 'automation-sap-concur',
    label: 'SAP Concur',
    description: 'SAP Concur profile, configuration lists and expense report metadata',
    category: 'finance-accounting',
    keywords: ['SAP Concur', 'lists', 'profiles', 'expense reports', 'configuration'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
