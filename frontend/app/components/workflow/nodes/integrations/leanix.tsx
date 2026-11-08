import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


// Unmodified SAP LeanIX wordmark from the official vendor website.
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/leanix.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const Component = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const LeanIXNode: NodeDefinition = {
    type: 'automation-leanix', label: 'SAP LeanIX', description: 'Protected fact-sheet metadata, current type facets and technical-fit filtered application reads.',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 110, height: 90, iconSize: 48 }, component: Component,
};
