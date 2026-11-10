import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const TaveIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/tave.svg" dark="/icons/tave-dark.svg" className={className} style={style} />
);

export const TaveNode: NodeDefinition = {
    type: 'automation-tave',
    label: 'Tave',
    category: 'crm-sales',
    description: 'Manage contacts, jobs, events, tasks and notes in VSCO Workspace',
    keywords: ['Tavé', 'VSCO', 'Workspace', 'photography', 'studio'],
    Icon: TaveIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TaveIcon} iconColor="" />),
};
