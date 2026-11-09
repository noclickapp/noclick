import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const CertSealIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/cert-seal.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
CertSealIcon.displayName = 'CertSealIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const CertSealNode: NodeDefinition = {
    type: 'automation-cert-seal',
    label: 'Cert Seal',
    description: 'Issue, email, verify and manage certificates',
    category: 'documents',
    Icon: CertSealIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CertSealIcon} iconColor="" />),
};
