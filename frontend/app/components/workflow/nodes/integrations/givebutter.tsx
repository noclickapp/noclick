import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const GivebutterIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/givebutter.svg" dark="/icons/givebutter-dark.svg" className={className} style={style} />
);

export const GivebutterNode: NodeDefinition = {
    type: 'automation-givebutter', category: 'nonprofit', label: 'Givebutter',
    description: 'Manage donor contacts, campaigns, activities, tags and funds; read donations and recurring plans; start workflows and agents from Givebutter events',
    keywords: ['fundraising', 'donations', 'donors', 'nonprofit', 'CRM'],
    Icon: GivebutterIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GivebutterIcon} iconColor="" />),
};
