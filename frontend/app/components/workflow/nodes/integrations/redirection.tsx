// Registers redirection.io in the canvas and integration catalog. The icon uses the
// provider's original blue symbol, which is legible on both light and dark tiles.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RedirectionIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/redirection.svg" alt="" aria-hidden="true" className={className} style={style} />
);

export const RedirectionNode: NodeDefinition = {
    type: 'automation-redirection',
    category: 'developer-tools',
    label: 'redirection.io',
    description: 'Manage redirects, draft rules, publishing, projects and domains',
    keywords: ['redirect', 'SEO', 'HTTP', 'redirection.io'],
    Icon: RedirectionIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RedirectionIcon} iconColor="" />),
};
