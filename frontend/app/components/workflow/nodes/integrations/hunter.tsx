import { forwardRef, memo, type CSSProperties, type ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

export const HunterIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/hunter.svg" alt="" aria-hidden="true"
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
    ),
);
HunterIcon.displayName = 'HunterIcon';
const HunterNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={HunterIcon} iconColor="" />;

export const HunterNode: NodeDefinition = {
    type: 'automation-hunter',
    label: 'Hunter',
    description: 'Hunter email discovery, verification, and outreach',
    Icon: HunterIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(HunterNodeComponent),
};
