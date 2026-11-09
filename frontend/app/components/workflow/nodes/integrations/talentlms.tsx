import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TalentLMSIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/talentlms.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TalentLMSNode: NodeDefinition = {
    type: 'automation-talentlms', category: 'courses', label: 'TalentLMS',
    description: 'Manage learners, courses, enrollments, progress and groups',
    Icon: TalentLMSIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TalentLMSIcon} iconColor="" />),
};
