import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://smartsheet.com

// Sourced brand artwork: https://www.smartsheet.com/sites/default/files/smartsheet-logo-blue-new.svg
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/smartsheet-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const SmartsheetNode: NodeDefinition = {
    type: 'automation-smartsheet',
    label: 'Smartsheet',
    description: 'Manage sheets, workspaces, rows, columns, and discussions',
    category: 'productivity',
    Icon: PreferredBrandIcon,
    iconColor: 'text-blue-500',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="text-blue-500" />
    )),
};
