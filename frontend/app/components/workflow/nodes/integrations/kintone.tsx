import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const KintoneIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/kintone.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const KintoneNode: NodeDefinition = {
    type: 'automation-kintone', category: 'databases-storage', label: 'Kintone',
    description: 'Automate app records, comments, process actions and cursor exports',
    Icon: KintoneIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KintoneIcon} iconColor="" />),
};
