// Sling exposes protected workforce catalogs and bounded calendar metadata.
// The shared editor uses the native schema; this node performs no schedule writes.
import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://getsling.com
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/sling-brand.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const SlingNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;

export const SlingNode: NodeDefinition = {
  type: 'automation-sling',
  label: 'Sling',
  description: 'Organization, workforce and calendar metadata',
  category: 'hr-recruiting',
  Icon: OfficialBrandIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: memo(SlingNodeComponent),
};
