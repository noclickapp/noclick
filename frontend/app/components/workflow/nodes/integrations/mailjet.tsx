import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.mailjet.com/

// Sourced brand artwork: https://www.mailjet.com/wp-content/themes/simpletexting-theme-blank/assets/images/logo-mailjet-sinch.svg
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/mailjet-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const MailjetNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="" />
);

export const MailjetNode: NodeDefinition = {
    type: 'automation-mailjet',
    label: 'Mailjet',
    description: 'Manage Mailjet contacts, campaigns, templates, and email',
    category: 'marketing',
    Icon: PreferredBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(MailjetNodeComponent),
};
