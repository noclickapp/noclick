// Registers CraftMyPDF in the discovered integration catalog.
// Uses the official publisher asset, with provenance recorded beside it.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const CraftmypdfIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/craftmypdf.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
CraftmypdfIcon.displayName = 'CraftmypdfIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const CraftmypdfNode: NodeDefinition = {
    type: 'automation-craftmypdf',
    label: 'CraftMyPDF',
    description: 'Generate PDFs and images, manage templates and edit PDF files',
    Icon: CraftmypdfIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CraftmypdfIcon} iconColor="" />),
};
