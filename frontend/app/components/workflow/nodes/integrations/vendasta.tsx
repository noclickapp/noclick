// Vendasta's canvas definition is discovered from its integration filename.
// Its component loads only when a Vendasta node appears on the canvas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Unmodified Vendasta symbol from Vendasta's official press kit.
const VendastaIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/vendasta.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={
            {
                ...style,
                '--brand-invert': 0,
                objectFit: 'contain',
            } as CSSProperties
        }
    />
);

const VendastaNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={VendastaIcon} iconColor="" />
);

export const VendastaNode: NodeDefinition = {
    type: 'automation-vendasta',
    label: 'Vendasta',
    description: 'Manage CRM contacts, companies, opportunities and schemas',
    category: 'crm-sales',
    keywords: ['CRM', 'contacts', 'companies', 'opportunities'],
    Icon: VendastaIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(VendastaNodeComponent),
};
