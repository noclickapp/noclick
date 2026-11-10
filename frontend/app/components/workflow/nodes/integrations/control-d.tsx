/* Control D's catalog and canvas definition. The backend-generated schema owns
   operation and credential forms so this module only supplies presentation. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ControlDIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/control-d.svg" dark="/icons/control-d-dark.svg" className={className} style={style} />
);

export const ControlDNode: NodeDefinition = {
    type: 'automation-control-d', category: 'cloud-hosting', label: 'Control D',
    description: 'Manage DNS profiles, filters, services, custom rules and endpoints',
    keywords: ['DNS', 'ControlD', 'network', 'filtering'],
    Icon: ControlDIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ControlDIcon} iconColor="" />),
};
