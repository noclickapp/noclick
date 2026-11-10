// Registers DNSimple's account-scoped metadata reads on the workflow canvas.
// The generated backend schema supplies operation forms and credentials.
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://dnsimple.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/dnsimple-brand-vector.svg" className={className} style={style} />
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

