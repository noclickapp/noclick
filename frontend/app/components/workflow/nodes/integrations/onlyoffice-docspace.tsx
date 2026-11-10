import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OnlyofficeDocspaceIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/onlyoffice-docspace.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const OnlyofficeDocspaceNode: NodeDefinition = {
    type: 'automation-onlyoffice-docspace', category: 'documents', label: 'ONLYOFFICE DocSpace',
    description: 'Create and rename rooms, folders and files; read users, history and access',
    Icon: OnlyofficeDocspaceIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OnlyofficeDocspaceIcon} iconColor="" />),
};
