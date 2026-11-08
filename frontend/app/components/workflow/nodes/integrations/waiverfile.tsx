// WaiverFile operations use the standard schema-driven workflow editor.
// Its official app icon identifies the account's waiver and event tools.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WaiverfileIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/waiverfile.png"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties}
    />
);

export const WaiverfileNode: NodeDefinition = {
    type: 'automation-waiverfile',
    label: 'WaiverFile',
    description:
        'Manage waivers, events, categories, forms and SMS subscriber exports',
    keywords: ['waiverfile', 'waivers', 'liability', 'event registration'],
    Icon: WaiverfileIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={WaiverfileIcon} iconColor="" />
    )),
};
