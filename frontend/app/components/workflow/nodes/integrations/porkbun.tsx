// Native metadata reads with Porkbun's official vector brand artwork.
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';
import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://porkbun.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/porkbun-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const PorkbunNode: NodeDefinition = {
  type: 'automation-porkbun',
  label: 'Porkbun',
  description: 'Read protected domain and DNS record metadata without DNS values',
  category: 'cloud-hosting',
  Icon: OfficialBrandIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: props => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
