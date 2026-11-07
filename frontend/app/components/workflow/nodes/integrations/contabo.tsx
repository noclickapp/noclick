// Native Contabo compute metadata node.
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://contabo.com

// Sourced brand artwork: https://cdn.contabo.com/contabo-logo-2.svg
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/contabo.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const Component = (props: NodeProps) => <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />;
export const ContaboNode: NodeDefinition = {
  type: 'automation-contabo', label: 'Contabo',
  description: 'Read protected instance, image, snapshot and image-capacity metadata',
  keywords: ['Contabo', 'cloud', 'VPS', 'compute', 'instance', 'image', 'snapshot', 'metadata'],
  Icon: PreferredBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: Component,
};
