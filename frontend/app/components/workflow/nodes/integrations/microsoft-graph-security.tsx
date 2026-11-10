import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
const GraphSecurityIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/microsoft-graph-security.svg" alt="" className={className} style={style} {...props} />,
);
GraphSecurityIcon.displayName = 'GraphSecurityIcon';
export const MicrosoftGraphSecurityNode: NodeDefinition = {
  type: 'automation-microsoft-graph-security', label: 'Microsoft Graph Security',
  description: 'Triage Defender alerts and incidents, monitor changes, and read Secure Score.',
  category: 'microsoft', keywords: ['Defender', 'security', 'incidents', 'alerts', 'secure score'],
  Icon: GraphSecurityIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 64 },
  component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GraphSecurityIcon} iconColor="" />),
};
