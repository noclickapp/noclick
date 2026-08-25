/** Data required by credential selection surfaces. */
export interface CredentialRequest {
    id: string;
    nodeId: string;
    type: 'credential';
    label: string;
    description: string;
    credentialType?: string;
    acceptedCredentialTypes?: string[];
    required: boolean;
    value?: string;
}
