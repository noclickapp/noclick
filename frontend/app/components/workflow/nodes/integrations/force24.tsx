import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const Force24Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/force24.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const Force24Node: NodeDefinition = {
    type: 'automation-force24', category: 'marketing', label: 'Force24',
    description: 'Sync contacts and marketing lists, send API campaigns, and read engagement reports',
    keywords: ['email marketing', 'marketing automation', 'contacts', 'campaigns'],
    Icon: Force24Icon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Force24Icon} iconColor="" />),
};
