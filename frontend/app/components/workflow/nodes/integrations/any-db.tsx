import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const AnyDbIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/any-db.svg" dark="/icons/any-db-dark.svg" className={className} style={style} />
);

export const AnyDbNode: NodeDefinition = {
    type: 'automation-any-db', category: 'databases-storage', label: 'Any Db',
    keywords: ['AnyDB', 'any_db'],
    description: 'Manage AnyDB teams, databases, records, file URLs, shares and webhooks',
    Icon: AnyDbIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AnyDbIcon} iconColor="" />),
};
