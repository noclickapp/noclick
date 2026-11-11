// Displays the MaintainX integration in the catalog and workflow canvas.
// Configuration and credentials come from the generated backend schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const MaintainxIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/maintainx.svg" dark="/icons/maintainx-dark.svg" className={className} style={style} />
);

export const MaintainxNode: NodeDefinition = {
    type: 'automation-maintainx', category: 'industry', label: 'MaintainX',
    description: 'Automate maintenance and react to work order, asset and inventory events',
    keywords: ['maintainx', 'cmms', 'maintenance', 'work orders', 'assets', 'inventory'],
    Icon: MaintainxIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MaintainxIcon} iconColor="" />),
};
