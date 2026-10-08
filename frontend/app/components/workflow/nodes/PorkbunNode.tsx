// Native metadata reads with the unchanged PNG linked by Porkbun's official guide.
import { ComponentProps } from 'react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';
import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://porkbun.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/porkbun-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const Icon = ({ className, style }: ComponentProps<'svg'>) => (
  <img src="/icons/porkbun.png" alt="" className={className} style={style} />
);
export const PorkbunNode: NodeDefinition = {
  type: 'automation-porkbun',
  label: 'Porkbun',
  description: 'Read protected domain and DNS record metadata without DNS values',
  Icon: OfficialBrandIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: props => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
