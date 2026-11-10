// KumpeApps account and family automation, discovered by the integration catalog.
// The provider's double-K mark comes from its official brand repository.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const KumpeAppsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/kumpeapps.svg" alt="" aria-hidden="true" className={className} style={style} />
);

export const KumpeAppsNode: NodeDefinition = {
    type: 'automation-kumpeapps', category: 'productivity', label: 'KumpeApps API',
    description: 'Manage chores and wishlists, track allowance and trigger on new transactions',
    keywords: ['KKid', 'KHome', 'family', 'chores', 'allowance', 'wishlist'],
    Icon: KumpeAppsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KumpeAppsIcon} iconColor="" />),
};
