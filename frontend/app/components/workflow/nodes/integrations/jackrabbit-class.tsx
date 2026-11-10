// Jackrabbit Class joins the workflow catalog through this definition.
// Its generated schema supplies the typed Customer API operation forms.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const JackrabbitClassIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/jackrabbit-class.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const JackrabbitClassNode: NodeDefinition = {
    type: 'automation-jackrabbit-class', category: 'courses', label: 'Jackrabbit Class',
    description: 'Manage families, students, contacts, classes, enrollments and attendance',
    Icon: JackrabbitClassIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JackrabbitClassIcon} iconColor="" />),
};
