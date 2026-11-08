import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const IdealpostcodesIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/idealpostcodes.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const IdealpostcodesNode: NodeDefinition = {
    type: 'automation-idealpostcodes', category: 'developer-tools', label: 'Ideal Postcodes',
    description: 'Find and cleanse addresses, validate contact details and manage key configurations',
    keywords: ['idealpostcodes', 'ideal-postcodes', 'postcode', 'address validation', 'address autocomplete', 'email validation', 'phone validation'],
    Icon: IdealpostcodesIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={IdealpostcodesIcon} iconColor="" />),
};
