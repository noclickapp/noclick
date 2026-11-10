import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://smartsheet.com

// Sourced brand artwork: https://www.smartsheet.com/sites/default/files/smartsheet-logo-blue-new.svg
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/smartsheet-preferred-brand.svg" dark="/icons/smartsheet-preferred-brand-dark.svg" className={className} style={style} />
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
