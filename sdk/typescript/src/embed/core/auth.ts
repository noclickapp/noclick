// Credential and OAuth management.

import { request } from './transport.js';

export interface CredentialInfo {
  id: string;
  type: string;
  name: string;
}

/** Check if a credential of the given type is available. */
export function hasCredential(credentialType: string): Promise<boolean> {
  return request('auth.hasCredential', { credentialType });
}

/** Trigger an OAuth flow (host opens popup). Resolves when complete, null if cancelled. */
export function requestCredential(credentialType: string): Promise<CredentialInfo | null> {
  return request('auth.requestCredential', { credentialType });
}

/** List all available credentials. */
export function listCredentials(): Promise<CredentialInfo[]> {
  return request('auth.listCredentials');
}

/** Create a non-OAuth credential (API key, token, etc). */
export function createCredential(
  credentialType: string,
  data: Record<string, unknown>,
  name?: string
): Promise<CredentialInfo | null> {
  return request('auth.createCredential', { credentialType, data, name });
}
