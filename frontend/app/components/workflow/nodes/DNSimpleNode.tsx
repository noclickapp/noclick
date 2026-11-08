// Registers DNSimple's account-scoped metadata reads on the workflow canvas.
// The generated backend schema supplies operation forms and credentials.
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';
import DNSimpleIcon from '~/components/icons/DNSimpleIcon';

import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://dnsimple.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/dnsimple-brand-vector.svg" alt="" aria-hidden="true" className={(className || '') + ' [--brand-invert:0] dark:[--brand-invert:1]'}
        style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
);

const DNSimpleNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
);
export const DNSimpleNode: NodeDefinition = {
    type: 'automation-dnsimple', category: 'cloud-hosting', label: 'DNSimple',
    description: 'Account-scoped domain and zone metadata without DNS records or control',
    keywords: ['DNSimple', 'domain state', 'zone metadata', 'expiry', 'DNS account'],
    Icon: OfficialBrandIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: DNSimpleNodeComponent,
};

