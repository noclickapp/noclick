import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SertifierIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/sertifier.webp" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const SertifierNode: NodeDefinition = {
    type: 'automation-sertifier',
    label: 'Sertifier',
    category: 'courses',
    description: 'Manage credential campaigns, recipients, certificates, badges, designs and templates',
    keywords: ['certificates', 'badges', 'digital credentials', 'learning'],
    Icon: SertifierIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SertifierIcon} iconColor="" />),
};
