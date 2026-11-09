// Registers Productlane in the workflow canvas and customer support catalog.
// The schema and credential metadata are discovered from the generated integration files.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ProductlaneIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/productlane.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={
            {
                ...style,
                '--brand-invert': 0,
                objectFit: 'contain',
            } as CSSProperties
        }
    />
);

export const ProductlaneNode: NodeDefinition = {
    type: 'automation-productlane',
    category: 'support',
    label: 'Productlane',
    description:
        'Manage customer feedback, conversations, contacts, companies and changelogs',
    keywords: ['feedback', 'customer support', 'roadmap', 'changelog'],
    Icon: ProductlaneIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={ProductlaneIcon} iconColor="" />
    )),
};
