/**
 * useServiceCredentialOptions returns the list of services that accept
 * credentials, read from the serialized node catalog the dashboard loader hands
 * over — so standalone surfaces (the create-credential dialog, Connections)
 * render the full service list at once, without the node registry or schemas.
 */

import { getServiceCredentialOptions, type ServiceCredentialOption } from '~/utils/credentialTypes';

export function useServiceCredentialOptions(): ServiceCredentialOption[] {
    return getServiceCredentialOptions();
}
