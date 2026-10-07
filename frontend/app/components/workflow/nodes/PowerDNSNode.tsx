// Supplied-key PowerDNS Authoritative metadata node. Original vendor PNG.
import { memo, type SVGProps } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';

export const PowerDNSIcon = ({ className, style }: SVGProps<SVGSVGElement>) => (
  <img src="/icons/powerdns.png" alt="PowerDNS" className={className} style={style} />
);

export const PowerDNSNode: NodeDefinition = {
  type: 'automation-powerdns',
  label: 'PowerDNS Authoritative',
  description: 'Read authoritative server, zone and RRset metadata',
  Icon: PowerDNSIcon as any,
  iconColor: '',
  dimensions: { width: 90, height: 90, iconSize: 48 },
  component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PowerDNSIcon as any} iconColor="" />),
};

