// Adds Formspark to the workflow canvas and integration catalog.
// Uses the official publisher icon and the shared schema-driven node UI.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FormsparkIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/formspark.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const FormsparkNode: NodeDefinition = {
    type: 'automation-formspark', category: 'forms', label: 'Formspark',
    description: 'Manage forms, workspaces, email templates and submissions',
    Icon: FormsparkIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FormsparkIcon} iconColor="" />),
};
