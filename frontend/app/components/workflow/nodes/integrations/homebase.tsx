import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.joinhomebase.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/homebase-brand-vector.svg" alt="" aria-hidden="true" className={(className || '') + ' [--brand-invert:0] dark:[--brand-invert:1]'}
        style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
);

const Component = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const HomebaseNode: NodeDefinition = {
    type: 'automation-homebase', label: 'Homebase', description: 'Protected company, configured locations and scoped employee metadata reads.',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 110, height: 90, iconSize: 48 }, component: Component,
};
