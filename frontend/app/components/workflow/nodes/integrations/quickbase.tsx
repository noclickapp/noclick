// Quickbase's self-registering definition exposes the generated operation catalog.
// The official brand icon identifies the service on the canvas and integration page.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const QuickbaseIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/quickbase.svg" dark="/icons/quickbase-dark.svg" className={className} style={style} />
);

export const QuickbaseNode: NodeDefinition = {
    type: 'automation-quickbase', category: 'databases-storage', label: 'Quickbase',
    description: 'Query and upsert records, run reports, and manage apps, tables and fields',
    keywords: ['Quick Base', 'records', 'database', 'low code'],
    Icon: QuickbaseIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={QuickbaseIcon} iconColor="" />),
};
