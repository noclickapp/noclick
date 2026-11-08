import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AddresszenIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/addresszen.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const AddresszenNode: NodeDefinition = {
    type: 'automation-addresszen', label: 'Addresszen',
    description: 'Verify addresses, emails and phone numbers; manage licensees, configurations and key usage',
    keywords: ['address zen', 'address validation', 'autocomplete', 'places', 'licensees'],
    Icon: AddresszenIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AddresszenIcon} iconColor="" />),
};
