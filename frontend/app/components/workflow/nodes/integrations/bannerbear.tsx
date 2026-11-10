import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Unmodified official Bannerbear brand icon from the provider website.
const BannerbearIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/bannerbear.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
        <img src="/icons/bannerbear-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
    </>
);

export const BannerbearNode: NodeDefinition = {
    type: 'automation-bannerbear',
    label: 'Bannerbear',
    description: 'Render personalized images, animations, and campaign batches',
    category: 'media',
    keywords: ['marketing', 'image', 'animation', 'template', 'batch', 'campaign'],
    Icon: BannerbearIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BannerbearIcon} iconColor="" />),
};
