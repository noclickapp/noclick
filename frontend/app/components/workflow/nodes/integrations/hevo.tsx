import { forwardRef, type CSSProperties, type ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HevoIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img {...props} className={`${className ?? ''} dark:hidden`} ref={ref} src="/icons/hevo.svg" alt="" aria-hidden="true"
                style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
            <img {...props} className={`${className ?? ''} hidden dark:block`} src="/icons/hevo-dark.svg" alt="" aria-hidden="true"
                style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
        </>
    ),
);
HevoIcon.displayName = 'HevoIcon';

export const HevoNode: NodeDefinition = {
    type: 'automation-hevo',
    label: 'Hevo',
    description: 'Regional pipeline, source and destination metadata, scheduling and workflow status',
    category: 'analytics-bi',
    Icon: HevoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={HevoIcon} iconColor="" />,
};
