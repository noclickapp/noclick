// NetLicensing's catalog and canvas definition uses its official avatar.
// Licensing operations and credential fields come from the generated schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const NetlicensingIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/netlicensing.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const NetlicensingNode: NodeDefinition = {
    type: 'automation-netlicensing', category: 'developer-tools', label: 'NetLicensing',
    description: 'Manage products, modules, license templates, licensees and licenses; validate entitlements and read transactions',
    keywords: ['software licensing', 'entitlements', 'Labs64', 'Netlicensing'],
    Icon: NetlicensingIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NetlicensingIcon} iconColor="" />),
};
