import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const EmeliaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/emelia.svg" dark="/icons/emelia-dark.svg" className={className} style={style} />
);

export const EmeliaNode: NodeDefinition = {
    type: 'automation-emelia', category: 'marketing', label: 'Emelia',
    description: 'Manage multichannel campaigns, prospect lists, email finding and verification',
    keywords: ['outreach', 'cold email', 'prospecting', 'leads', 'email verification'],
    Icon: EmeliaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EmeliaIcon} iconColor="" />),
};
