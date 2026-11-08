import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Unmodified icon from Atlassian's official logo library; see the adjacent icon provenance sidecar.
const JiraServiceManagementIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/jiraservicemanagement.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const JiraServiceManagementNode: NodeDefinition = {
    type: 'automation-jiraservicemanagement',
    label: 'Jira Service Management',
    description: 'Automate service requests, customers, queues and SLAs',
    category: 'support',
    keywords: ['JSM', 'service desk', 'help desk', 'ITSM', 'Atlassian'],
    Icon: JiraServiceManagementIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={JiraServiceManagementIcon} iconColor="" />
    )),
};
