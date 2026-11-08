// Discover the Freshteam tile through the self-registering integration catalog.
// Keep the official wordmark and native metadata operations together.
import { forwardRef, type CSSProperties, type ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Official Freshteam developer wordmark; preserve its aspect ratio.
export const FreshteamIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/freshteam.svg" alt="" aria-hidden="true"
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
    ),
);
FreshteamIcon.displayName = 'FreshteamIcon';
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={FreshteamIcon} iconColor="" />;
export const FreshteamNode: NodeDefinition = {
    type: 'automation-freshteam', label: 'Freshteam',
    description: 'Organization, job, applicant and employee metadata',
    Icon: FreshteamIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: Component,
};
