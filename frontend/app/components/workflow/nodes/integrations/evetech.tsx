// Registers EVE Swagger Interface in the canvas and integration catalog.
// Uses the official EVE logo while the generated backend schema supplies its operations and credential form.
import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const EvetechIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/evetech.svg" alt="" className={className} style={{ ...style, objectFit: 'contain', backgroundColor: '#111827', borderRadius: 8, padding: 6 }} {...props} />
    ),
);
EvetechIcon.displayName = 'EvetechIcon';

export const EvetechNode: NodeDefinition = {
    type: 'automation-evetech', label: 'EVE Swagger Interface', category: 'industry',
    description: 'EVE Online markets, character assets, wallet, mail and calendar; poll for new mail',
    Icon: EvetechIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo(function EvetechNodeComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={EvetechIcon} iconColor="" />;
    }),
};
