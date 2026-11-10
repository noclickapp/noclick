// Declares Echtpost in the integration catalog and workflow canvas.
// The backend schema supplies its operations and API-key connection form.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const EchtpostIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/echtpost.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const EchtpostNode: NodeDefinition = {
    type: 'automation-echtpost', category: 'marketing', label: 'Echtpost',
    description: 'Send postcards and manage contacts, groups, templates and designs',
    Icon: EchtpostIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EchtpostIcon} iconColor="" />),
};
