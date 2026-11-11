// Microsoft Excel automation node definition.
// Provides comprehensive Excel workbook operations via Microsoft Graph API.
// Supports workbooks, worksheets, ranges, tables, charts, and named items.

import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 60 };

// Official Microsoft Excel 2025 icon SVG
const ExcelIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/excel.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const ExcelNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={ExcelIcon}
            iconColor=""
            width={DIMENSIONS.width}
            height={DIMENSIONS.height}
            iconSize={DIMENSIONS.iconSize}
        />
    );
};

export const ExcelNode: NodeDefinition = {
    type: 'automation-excel',
    label: 'Excel',
    description: 'Excel automation',
    Icon: ExcelIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ExcelNodeComponent),
};
