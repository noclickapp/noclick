// GitLab DevOps automation node definition.
// Provides workflow integration with the GitLab REST API v4 (projects, issues,
// merge requests, repository, CI/CD, releases) plus a webhook trigger for
// project hook events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const GitLabIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/gitlab.svg" alt="" className={className} style={style} {...props} />
));
GitLabIcon.displayName = 'GitLabIcon';

const GitLabNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={GitLabIcon} iconColor="" />;
};

export const GitLabNode: NodeDefinition = {
    type: 'automation-gitlab',
    label: 'GitLab',
    description: 'GitLab DevOps automation',
    Icon: GitLabIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GitLabNodeComponent),
};
