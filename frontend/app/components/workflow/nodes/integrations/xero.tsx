import type { CSSProperties as BrandCSSProperties } from 'react';
import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Sourced brand artwork: https://logos.composio.dev/api/xero
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/xero-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

export const XeroNode: NodeDefinition = {
    type: 'automation-xero',
    label: 'Xero',
    description: 'Accounting, invoices, contacts, reports, and projects',
    category: 'finance-accounting',
    Icon: PreferredBrandIcon,
    iconColor: 'text-cyan-500',
    dimensions: DIMENSIONS,
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="text-cyan-500" />
    )),
};
