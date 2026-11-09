import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const JiraSoftwareServerIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/jira-software-server.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
JiraSoftwareServerIcon.displayName = 'JiraSoftwareServerIcon';

export const JiraSoftwareServerNode: NodeDefinition = {
    type: 'automation-jira-software-server',
    label: 'Jira Software Server',
    description: 'Automate issues, comments, worklogs, projects, boards and sprints on Jira Server or Data Center.',
    category: 'developer-tools',
    keywords: ['Atlassian', 'Jira Data Center', 'JQL', 'scrum', 'kanban'],
    Icon: JiraSoftwareServerIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JiraSoftwareServerIcon} iconColor="" />),
};
