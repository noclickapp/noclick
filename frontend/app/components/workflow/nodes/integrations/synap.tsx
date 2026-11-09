// Synap learning and assessment automation, discovered with its generated schema.
// The official mark identifies the connected learning platform in the catalog and canvas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SynapIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/synap.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);
export const SynapNode: NodeDefinition = {
    type: 'automation-synap', category: 'courses', label: 'Synap',
    description: 'Automate learners, study groups, exams, attempts and learning records, and receive Synap events',
    keywords: ['learning', 'LMS', 'assessment', 'exam', 'student'],
    Icon: SynapIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SynapIcon} iconColor="" />),
};
