import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


// Unmodified logo from https://www.adyen.com/press-and-media/presskit
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/adyen.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
);

const Component = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const AdyenNode: NodeDefinition = {
    type: 'automation-adyen', category: 'finance-accounting', label: 'Adyen', description: 'API credential, company, merchant and store metadata, store description updates and payment link status.',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 110, height: 90, iconSize: 48 }, component: memo(Component),
};
