// Native Contabo compute metadata node.
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://contabo.com

// Sourced brand artwork: https://cdn.contabo.com/contabo-logo-2.svg
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/contabo.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const Component = (props: NodeProps) => <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />;
export const ContaboNode: NodeDefinition = {
  type: 'automation-contabo', category: 'cloud-hosting', label: 'Contabo',
  description: 'Read cloud metadata and trigger on new instances, image updates and new snapshots',
  keywords: ['Contabo', 'cloud', 'VPS', 'compute', 'instance', 'image', 'snapshot', 'metadata', 'trigger', 'poll'],
  Icon: PreferredBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: Component,
};
