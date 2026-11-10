// Voluum canvas definition, discovered from this integration module.
// Uses the existing automation canvas with the vendor artwork.
import { forwardRef, memo, type ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Exact official developer-site SVG; full wordmark, no tracing or recoloring.

import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://voluum.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/voluum-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const VoluumIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
  function VoluumIcon(props, ref) {
    return <img ref={ref} src="/icons/voluum.svg" alt="Voluum" {...props} />;
  },
);

export const VoluumNode: NodeDefinition = {
  type: 'automation-voluum',
  label: 'Voluum',
  description: 'Manage campaign, offer, lander and traffic source metadata; read aggregate reports',
  category: 'marketing',
  Icon: OfficialBrandIcon,
  iconColor: '',
  dimensions: { width: 110, height: 90, iconSize: 72 },
  component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
