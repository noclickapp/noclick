import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const IntelliprintIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/intelliprint.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const IntelliprintNode: NodeDefinition = {
    type: 'automation-intelliprint', category: 'documents', label: 'Intelliprint',
    description: 'Send letters and postcards, manage backgrounds, mailing lists and recipients',
    keywords: ['print', 'physical mail', 'letters', 'postcards', 'direct mail'],
    Icon: IntelliprintIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={IntelliprintIcon} iconColor="" />),
};
