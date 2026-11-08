/** BugHerd's native read node uses the shared operation editor and credential picker.
 * Its original vendor logo is retained; connection evidence reads the organization endpoint.
 */
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://bugherd.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/bugherd-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const BugHerdNode: NodeDefinition = {
    type: 'automation-bugherd',
    label: 'BugHerd',
    description: 'Read organization, projects, feedback tasks, comments and memberships',
    category: 'developer-tools',
    keywords: ['bugherd', 'feedback', 'bugs', 'tasks', 'projects', 'comments'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
