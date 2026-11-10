// Supplied-key PowerDNS Authoritative metadata node. Original vendor PNG.
import { memo, type SVGProps } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.powerdns.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/powerdns-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const PowerDNSIcon = ({ className, style }: SVGProps<SVGSVGElement>) => (
  <img src="/icons/powerdns.png" alt="PowerDNS" className={className} style={style} />
);

export const PowerDNSNode: NodeDefinition = {
  type: 'automation-powerdns',
  label: 'PowerDNS Authoritative',
  description: 'Read authoritative server, zone and RRset metadata',
  category: 'cloud-hosting',
  Icon: OfficialBrandIcon,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
