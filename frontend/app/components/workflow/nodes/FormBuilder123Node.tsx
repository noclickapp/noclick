import type { SVGProps } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.123formbuilder.com/brand-guidelines/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/123formbuilder-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const FormBuilder123Icon = ({ className, style }: SVGProps<SVGSVGElement>) => (
    <img src="/icons/123formbuilder.svg" alt="123FormBuilder" className={className} style={style} />
);

export const FormBuilder123Node: NodeDefinition = {
    type: 'automation-123formbuilder',
    label: '123FormBuilder',
    description: 'Read form, field and submission metadata; organize forms and folders',
    category: 'forms',
    keywords: ['123', 'forms', 'surveys', 'submissions', 'folders'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />,
};
