import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const MicrosoftExchangeIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/microsoft-exchange.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
MicrosoftExchangeIcon.displayName = 'MicrosoftExchangeIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const MicrosoftExchangeNode: NodeDefinition = {
    type: 'automation-microsoft-exchange',
    label: 'Microsoft Exchange',
    description: 'Exchange Online mail, folders, calendars and contacts',
    category: 'microsoft',
    keywords: ['Exchange Online', 'Microsoft 365', 'mail', 'calendar', 'contacts'],
    Icon: MicrosoftExchangeIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MicrosoftExchangeIcon} iconColor="" />),
};
