// Credly's catalog definition exposes badge automation in the courses section.
// The official provider icon identifies the integration on the canvas and catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CredlyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/credlys-acclaim-platform.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const CredlyNode: NodeDefinition = {
    type: 'automation-credlys-acclaim-platform', category: 'courses', label: 'Credly',
    description: 'Issue, replace and revoke badges, manage templates and read organizations',
    keywords: ['Acclaim', 'digital credentials', 'certificates', 'badges'],
    Icon: CredlyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CredlyIcon} iconColor="" />),
};
