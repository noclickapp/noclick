// Cloudsmith's discoverable node definition for the workflow canvas and catalog.
// Configuration and credential forms come from the generated backend schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CloudsmithIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/cloudsmith.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const CloudsmithNode: NodeDefinition = {
    type: 'automation-cloudsmith', category: 'developer-tools', label: 'Cloudsmith',
    description: 'Manage artifact repositories, packages, tags, scans and entitlement tokens',
    keywords: ['artifacts', 'packages', 'registry', 'software supply chain'],
    Icon: CloudsmithIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CloudsmithIcon} iconColor="" />),
};
