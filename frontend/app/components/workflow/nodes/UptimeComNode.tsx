// Uptime.com reads authenticated-user and approved monitoring metadata.
// This native editor definition displays the unaltered official public wordmark.
import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';
const UptimeComIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/uptimecom.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />,
);
UptimeComIcon.displayName = 'UptimeComIcon';
export const UptimeComNode: NodeDefinition = {
    type: 'automation-uptimecom', label: 'Uptime.com',
    description: 'Read scoped check, tag, outage, status-page and statistics metadata',
    keywords: ['Uptime.com', 'checks', 'monitoring', 'outages', 'status pages', 'statistics'],
    Icon: UptimeComIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={UptimeComIcon} iconColor="" />),
};
