import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AccredibleCertificatesIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/accredible-certificates.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const AccredibleCertificatesNode: NodeDefinition = {
    type: 'automation-accredible-certificates', category: 'courses', label: 'Accredible Certificates',
    description: 'Issue and manage certificates, badges, recipients and achievement groups',
    keywords: ['accredible', 'certificate', 'badge', 'credential', 'certification'],
    Icon: AccredibleCertificatesIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AccredibleCertificatesIcon} iconColor="" />),
};
