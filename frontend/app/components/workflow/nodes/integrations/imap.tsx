import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { Inbox } from 'lucide-react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// No one provider's mark: the same node connects Yahoo, iCloud, Zoho, Fastmail and company mailboxes.
const ImapNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={Inbox} iconColor="text-foreground" />;

export const ImapNode: NodeDefinition = {
    type: 'automation-imap',
    label: 'Email (IMAP/SMTP)',
    description: 'Read, file and send mail from Yahoo, AOL, iCloud, Zoho, Fastmail, GMX or any IMAP mailbox',
    keywords: [
        'IMAP',
        'SMTP',
        'Yahoo Mail',
        'AOL Mail',
        'iCloud Mail',
        'Zoho Mail',
        'Fastmail',
        'GMX',
        'mail.com',
        'mailbox',
        'inbox',
        'email account',
        'app password',
        'new email',
    ],
    category: 'communication',
    Icon: Inbox,
    iconColor: 'text-foreground',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(ImapNodeComponent),
};
