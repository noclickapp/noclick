// Uptime.com reads authenticated-user and approved monitoring metadata.
// This native editor definition displays the unaltered official public wordmark.
import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://uptime.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/uptimecom-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const UptimeComNode = {
    type: 'automation-uptimecom', category: 'monitoring', label: 'Uptime.com',
    description: 'Read scoped check, tag, outage, status-page and statistics metadata',
    keywords: ['Uptime.com', 'checks', 'monitoring', 'outages', 'status pages', 'statistics'],
    Icon: OfficialBrandIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
} satisfies NodeDefinition;
