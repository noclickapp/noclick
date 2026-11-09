// Exposes Drop Cowboy's messaging and contact-list actions in the workflow catalog.
// The official provider logo identifies the account users connect.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DropCowboyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/drop-cowboy.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const DropCowboyNode: NodeDefinition = {
    type: 'automation-drop-cowboy', category: 'communication', label: 'Drop Cowboy',
    description: 'Send ringless voicemail and SMS, manage contact lists, and read brands, media and number pools',
    keywords: ['sms', 'text message', 'ringless voicemail', 'contacts'],
    Icon: DropCowboyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DropCowboyIcon} iconColor="" />),
};
