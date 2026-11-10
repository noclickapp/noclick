// Adds Paradym to the workflow canvas and integration catalog. The official publisher icon identifies its wallet and credential operations.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const ParadymIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/paradym.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/paradym-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
    ),
);
ParadymIcon.displayName = 'ParadymIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const ParadymNode: NodeDefinition = {
    type: 'automation-paradym',
    label: 'Paradym',
    description: 'Wallets, credential templates, issuance and verification',
    category: 'developer-tools',
    Icon: ParadymIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ParadymIcon} iconColor="" />),
};
