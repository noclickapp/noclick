// Dummy placeholder nodes for various integrations.
// These nodes display SVG icons from the public folder and serve as placeholders
// until full integration implementations are added.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Helper to create an icon component from an SVG path in /public/icons/
// The component renders an img element that accepts className and style props
const createSvgIcon = (filename: string) => {
    const IconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
        ({ className, style, ...props }, ref) => (
            <img
                ref={ref}
                src={`/icons/${filename}`}
                alt=""
                className={className}
                style={style}
                {...props}
            />
        )
    );
    IconComponent.displayName = `SvgIcon(${filename})`;
    return IconComponent;
};

// Create icon components for each SVG
const CloudflareIcon = createSvgIcon('cloudflare.svg');
const DropboxIcon = createSvgIcon('dropbox.svg');
const ExcelIcon = createSvgIcon('excel2.svg');
const GoogleCalendarIcon = createSvgIcon('google-calendar.svg');
const MailchimpIcon = createSvgIcon('mailchimp.svg');
const MondayIcon = createSvgIcon('monday.svg');
const NotionIcon = createSvgIcon('notion.svg');
const RedditIcon = createSvgIcon('reddit.svg');
const SalesforceIcon = createSvgIcon('salesforce.svg');
const ShopifyIcon = createSvgIcon('shopify.svg');
const SpotifyIcon = createSvgIcon('spotify.svg');

// Helper to create a dummy node definition
const createDummyNode = (
    type: string,
    label: string,
    description: string,
    Icon: SvgIconComponent
): NodeDefinition => {
    const NodeComponent = (props: NodeProps) => (
        <AutomationNode {...props} Icon={Icon} iconColor="" />
    );

    return {
        type,
        label,
        description,
        Icon,
        iconColor: '',
        dimensions: DIMENSIONS,
        component: memo(NodeComponent),
    };
};

// Export all dummy node definitions
export const CloudflareNode = createDummyNode(
    'automation-cloudflare',
    'Cloudflare',
    'Cloudflare services',
    CloudflareIcon
);

export const DropboxNode = createDummyNode(
    'automation-dropbox',
    'Dropbox',
    'Dropbox storage',
    DropboxIcon
);

export const ExcelNode = createDummyNode(
    'automation-excel',
    'Excel',
    'Excel spreadsheets',
    ExcelIcon
);

export const GoogleCalendarNode = createDummyNode(
    'automation-google-calendar',
    'Google Calendar',
    'Calendar events',
    GoogleCalendarIcon
);

export const MailchimpNode = createDummyNode(
    'automation-mailchimp',
    'Mailchimp',
    'Email marketing',
    MailchimpIcon
);

export const MondayNode = createDummyNode(
    'automation-monday',
    'Monday.com',
    'Monday.com projects',
    MondayIcon
);

export const NotionNode = createDummyNode(
    'automation-notion',
    'Notion',
    'Notion workspace',
    NotionIcon
);

export const RedditNode = createDummyNode(
    'automation-reddit',
    'Reddit',
    'Reddit automation',
    RedditIcon
);

export const SalesforceNode = createDummyNode(
    'automation-salesforce',
    'Salesforce',
    'Salesforce CRM',
    SalesforceIcon
);

export const ShopifyNode = createDummyNode(
    'automation-shopify',
    'Shopify',
    'Shopify e-commerce',
    ShopifyIcon
);

export const SpotifyNode = createDummyNode(
    'automation-spotify',
    'Spotify',
    'Spotify music',
    SpotifyIcon
);

// Export all dummy nodes as an array for easy import
export const DUMMY_NODES: NodeDefinition[] = [
    CloudflareNode,
    DropboxNode,
    ExcelNode,
    GoogleCalendarNode,
    MailchimpNode,
    MondayNode,
    NotionNode,
    RedditNode,
    SalesforceNode,
    ShopifyNode,
    SpotifyNode,
];
