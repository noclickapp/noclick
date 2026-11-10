import { forwardRef, type CSSProperties, type ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const IterableIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img {...props} className={`${className ?? ''} dark:hidden`} ref={ref} src="/icons/iterable-preferred-brand.svg" alt="" aria-hidden="true"
                style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
            <img {...props} className={`${className ?? ''} hidden dark:block`} src="/icons/iterable-preferred-brand-dark.svg" alt="" aria-hidden="true"
                style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
        </>
    ),
);
IterableIcon.displayName = 'IterableIcon';

export const IterableNode: NodeDefinition = {
    type: 'automation-iterable',
    label: 'Iterable',
    description: 'Iterable users, lists, events, campaigns, templates, and journeys',
    category: 'marketing',
    Icon: IterableIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={IterableIcon} iconColor="" />,
};
