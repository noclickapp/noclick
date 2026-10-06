// Preserves real Drip and Mautic generated credential definitions for UI regressions.
// The nested wrappers are reconstructed from their original Annotated unions; the overwritten original generated files are not claimed as retained artifacts.
// Provenance and original hashes are recorded in the task-local source-readiness report.

const dripDefinitions = {
    "DripAPITokenCredential": {
      "properties": {
        "credential_type": {
          "const": "drip_api_token",
          "default": "drip_api_token",
          "title": "Credential Type",
          "type": "string",
          "ui:hidden": true
        },
        "api_token": {
          "description": "Existing personal API token from Drip User Settings. Do not replace it to connect.",
          "title": "API Token",
          "type": "string",
          "ui:widget": "password"
        }
      },
      "required": [
        "api_token"
      ],
      "title": "Drip API Token",
      "type": "object",
      "x-credential-instructions": "For private integrations with your own account. Drip requires OAuth for public integrations. Sent as HTTP Basic username with an empty password.",
      "x-credential-url": "https://help.drip.com/hc/en-us/articles/4424695636237-User-Settings-Settings-and-API-Token"
    },
    "DripOAuthCredential": {
      "properties": {
        "credential_type": {
          "const": "drip_oauth",
          "default": "drip_oauth",
          "title": "Credential Type",
          "type": "string",
          "ui:hidden": true
        },
        "access_token": {
          "title": "Access Token",
          "type": "string",
          "ui:widget": "password"
        },
        "token_type": {
          "const": "bearer",
          "default": "bearer",
          "title": "Token Type",
          "type": "string"
        },
        "scope": {
          "const": "public",
          "default": "public",
          "title": "Scope",
          "type": "string"
        }
      },
      "required": [
        "access_token"
      ],
      "title": "Drip OAuth",
      "type": "object",
      "x-credential-type": "oauth",
      "x-credential-url": "https://www.getdrip.com/user/applications",
      "x-oauth-provider": "drip",
      "x-oauth-scopes": [
        "public"
      ]
    },
};

const mauticDefinitions = {
    "MauticBasicCredential": {
      "properties": {
        "instance_url": {
          "description": "Public HTTPS installation URL, including its subdirectory if any; omit /api.",
          "placeholder": "https://mautic.example.com",
          "title": "Mautic Installation URL",
          "type": "string"
        },
        "credential_type": {
          "const": "mautic_basic",
          "default": "mautic_basic",
          "title": "Credential Type",
          "type": "string",
          "ui:hidden": true
        },
        "username": {
          "minLength": 1,
          "title": "Username",
          "type": "string"
        },
        "password": {
          "title": "Password",
          "type": "string",
          "ui:widget": "password"
        }
      },
      "required": [
        "instance_url",
        "username",
        "password"
      ],
      "title": "MauticBasicCredential",
      "type": "object",
      "x-credential-instructions": "Enable the API and Basic authentication in Mautic Configuration > API Settings. Use a dedicated Mautic user with the required contact and segment role permissions.",
      "x-credential-url": "https://devdocs.mautic.org/en/7.2/rest_api/authentication.html"
    },
    "MauticOAuth2Credential": {
      "properties": {
        "instance_url": {
          "description": "Public HTTPS installation URL, including its subdirectory if any; omit /api.",
          "placeholder": "https://mautic.example.com",
          "title": "Mautic Installation URL",
          "type": "string"
        },
        "credential_type": {
          "const": "mautic_oauth2",
          "default": "mautic_oauth2",
          "title": "Credential Type",
          "type": "string",
          "ui:hidden": true
        },
        "client_id": {
          "minLength": 1,
          "title": "Client ID",
          "type": "string"
        },
        "client_secret": {
          "title": "Client Secret",
          "type": "string",
          "ui:widget": "password"
        },
        "access_token": {
          "title": "Access Token",
          "type": "string",
          "ui:widget": "password"
        },
        "refresh_token": {
          "title": "Refresh Token",
          "type": "string",
          "ui:widget": "password"
        },
        "expires_at": {
          "description": "UTC ISO 8601 expiry calculated from the token response's expires_in.",
          "title": "Token Expiry",
          "type": "string"
        }
      },
      "required": [
        "instance_url",
        "client_id",
        "client_secret",
        "access_token",
        "refresh_token",
        "expires_at"
      ],
      "title": "MauticOAuth2Credential",
      "type": "object",
      "x-credential-instructions": "Complete Mautic's user Authorization Code flow with your own API client, then enter its token response and client credentials here. NoClick refreshes saved tokens. This is manual token entry; no OAuth popup. Client Credentials tokens are not supported by this user identity connection.",
      "x-credential-url": "https://devdocs.mautic.org/en/7.2/rest_api/authentication.html"
    },
};

function nullableDiscriminatedCredentials(definitions: Record<string, any>, names: string[]) {
    return {
        $defs: definitions,
        properties: {
            credentials: {
                anyOf: [
                    {
                        discriminator: {
                            propertyName: 'credential_type',
                            mapping: Object.fromEntries(names.map(name => [
                                definitions[name].properties.credential_type.const, `#/$defs/${name}`,
                            ])),
                        },
                        oneOf: names.map(name => ({ $ref: `#/$defs/${name}` })),
                    },
                    { type: 'null' },
                ],
                default: null,
                description: 'Credentials for this node (optional if using environment variables)',
                title: 'Credentials',
            },
        },
    };
}

export const dripCredentialSchema = nullableDiscriminatedCredentials(
    dripDefinitions, ['DripOAuthCredential', 'DripAPITokenCredential'],
);
export const mauticCredentialSchema = nullableDiscriminatedCredentials(
    mauticDefinitions, ['MauticBasicCredential', 'MauticOAuth2Credential'],
);
