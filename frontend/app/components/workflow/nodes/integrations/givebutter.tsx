import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GivebutterIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/givebutter.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const GivebutterNode: NodeDefinition = {
    type: 'automation-givebutter', label: 'Givebutter',
    description: 'Manage donor contacts, campaigns, activities, tags and funds; read donations and recurring plans',
    keywords: ['fundraising', 'donations', 'donors', 'nonprofit', 'CRM'],
    Icon: GivebutterIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GivebutterIcon} iconColor="" />),
};
