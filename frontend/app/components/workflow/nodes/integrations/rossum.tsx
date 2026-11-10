import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Rossum brand mark from https://rossum.ai
const RossumIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/rossum.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={RossumIcon} iconColor="" />;
export const RossumNode: NodeDefinition = {
    type: 'automation-rossum', category: 'documents', label: 'Rossum',
    description: 'Rossum organization, queue and private document workflows',
    Icon: RossumIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: memo(Component),
};
