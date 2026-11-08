// Native company enrichment and company-search configuration uses the generated schema.
// The official SVG is retained unchanged; saving a key never issues a paid probe.
import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const PeopleDataLabsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/people-data-labs.svg" alt="" className={className} style={style} {...props} />,
);
PeopleDataLabsIcon.displayName = 'PeopleDataLabsIcon';

export const PeopleDataLabsNode: NodeDefinition = {
    type: 'automation-people-data-labs',
    label: 'People Data Labs',
    description: 'Explicit company enrichment and bounded company search using provider credits',
    category: 'crm-sales',
    keywords: ['People Data Labs', 'PDL', 'company', 'firmographics', 'enrichment', 'search'],
    Icon: PeopleDataLabsIcon,
    iconColor: '#34344e',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={PeopleDataLabsIcon} iconColor="#34344e" />,
};
