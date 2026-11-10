// DataForSEO v3 SEO queries and asynchronous Google organic SERP tasks.
// The workflow shows bounded results and keeps API credentials private.
import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://github.com/dataforseo/n8n-nodes-dataforseo
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/dataforseo-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const DataForSEOIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/dataforseo.svg" alt="" className={className} style={style} {...props} />
    ),
);
DataForSEOIcon.displayName = 'DataForSEOIcon';

export const DataForSEONode: NodeDefinition = {
    type: 'automation-dataforseo',
    label: 'DataForSEO',
    description: 'Query keyword, domain and backlink data, submit SERP tasks, and collect existing task results. Queries may consume provider credits.',
    category: 'marketing',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
