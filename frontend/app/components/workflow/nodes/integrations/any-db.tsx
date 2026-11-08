import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AnyDbIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/any-db.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const AnyDbNode: NodeDefinition = {
    type: 'automation-any-db', category: 'databases-storage', label: 'Any Db',
    keywords: ['AnyDB', 'any_db'],
    description: 'Manage AnyDB teams, databases, records, file URLs, shares and webhooks',
    Icon: AnyDbIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AnyDbIcon} iconColor="" />),
};
