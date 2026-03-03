// Maps workflow node types to their external resource URLs and brand colors.
// Used by FlowCanvas to render the "Open" pill when a node has a resource ID filled in.

export interface ExternalLinkConfig {
    field: string;
    urlTemplate: (id: string) => string;
    label: string;
    bgColor: string;
}

export const EXTERNAL_LINK_CONFIG: Record<string, ExternalLinkConfig> = {
    'automation-google-sheets': {
        field: 'spreadsheet_id',
        urlTemplate: (id) => `https://docs.google.com/spreadsheets/d/${id}`,
        label: 'Open Sheet',
        bgColor: '#0F9D58',
    },
    'automation-google-docs': {
        field: 'document_id',
        urlTemplate: (id) => `https://docs.google.com/document/d/${id}`,
        label: 'Open Doc',
        bgColor: '#4285F4',
    },
    'automation-google-slides': {
        field: 'presentation_id',
        urlTemplate: (id) => `https://docs.google.com/presentation/d/${id}/edit`,
        label: 'Open Slides',
        bgColor: '#F4B400',
    },
    'automation-google-forms': {
        field: 'form_id',
        urlTemplate: (id) => `https://docs.google.com/forms/d/${id}/edit`,
        label: 'Open Form',
        bgColor: '#7248B9',
    },
    'automation-google-drive': {
        field: 'file_id',
        urlTemplate: (id) => `https://drive.google.com/file/d/${id}/view`,
        label: 'Open File',
        bgColor: '#1FA463',
    },
};
