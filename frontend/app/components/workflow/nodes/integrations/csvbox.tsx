// Csvbox's sheet and importer actions appear in the integration catalog and canvas.
// The publisher's unmodified logo identifies the service in both places.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CsvboxIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/csvbox.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CsvboxNode: NodeDefinition = {
    type: 'automation-csvbox',
    category: 'developer-tools',
    label: 'Csvbox',
    description: 'Manage sheets, import columns, destinations, validation and transforms',
    keywords: ['csv', 'importer', 'data import', 'sheets'],
    Icon: CsvboxIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CsvboxIcon} iconColor="" />),
};
