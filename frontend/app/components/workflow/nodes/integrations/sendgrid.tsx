import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://sendgrid.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/sendgrid-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const SendGridNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="text-blue-500" />
);

export const SendGridNode: NodeDefinition = {
    type: 'automation-sendgrid',
    label: 'SendGrid',
    description: 'Send email, manage contacts and templates, and inspect delivery activity',
    Icon: OfficialBrandIcon,
    iconColor: 'text-blue-500',
    dimensions: DIMENSIONS,
    component: memo(SendGridNodeComponent),
};
