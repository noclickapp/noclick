// What an account's app is called, by its credential type, with its brand's casing: the name every connect surface
// heads with. Apart from the provide flow so a card can name an app before the flow (and every sign-in) has loaded.
import { agentCompanyOf } from '~/lib/agentCredentialModel';
import { credentialAppName } from '~/utils/credentialIcons';
import { fixWordCasing } from '~/utils/credentialLabels';
import { getServiceForCredentialType } from '~/utils/credentialTypes';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';

/** Convert credential_type to human-readable label */
export function formatCredentialType(type: string): string {
    return (
        type
            .replace(/_oauth$/, '')
            .replace(/_pat$/, ' PAT')
            .replace(/_api_key$/, ' API Key')
            .replace(/_bot_token$/, ' Bot Token')
            .replace(/_api_token$/, ' API Token')
            .replace(/_bearer_token$/, ' Bearer Token')
            .replace(/_integration_token$/, ' Integration Token')
            .replace(/_access_token$/, ' Access Token')
            .replace(/_connection_string$/, ' Connection String')
            .replace(/_/g, ' ')
            .replace(/\b\w/g, (c) => c.toUpperCase())
            // "Whatsapp Qr" → "WhatsApp QR": Title Case can't know acronyms/brands.
            .split(' ')
            .map((w) => fixWordCasing(w))
            .join(' ')
    );
}

/** The app a request is for, as Connections names it: an AI account's company ("Anthropic"), else the app as the
 *  catalog names it ("Notion"), else its sign-in's provider, else its type. */
export function appNameForCredentialType(credentialType: string): string {
    return (
        agentCompanyOf(credentialType)?.title ??
        getServiceForCredentialType(credentialType)?.label ??
        credentialAppName(credentialType) ??
        getProviderConfigByCredentialType(credentialType)?.name ??
        formatCredentialType(credentialType)
    );
}
