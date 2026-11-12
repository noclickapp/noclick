// What a bridge link asks, in words: the page's heading and the title, description and picture its link unfurls to,
// from the questions the page shows its holder (GET /api/builder-bridge/{id}) and nothing more. One source, so the
// page, its preview in a chat and the landing's drawing of that preview read the same.
import { fixWordCasing } from '~/utils/credentialLabels';
import { CLOSED_ART, QUESTION_ART, connectImage, previewImage } from '~/lib/linkPreviews';
import type { BridgePayload } from './BuilderBridge';

// How a credential type says it signs in, after its app's name ("_login", "_personal_api_key", "_service_account"):
// never part of what a person connects.
const SIGN_IN_SUFFIX = new RegExp(
  '_(?:(?:personal|project|developer|management|integration|bearer|bot|auth|page_access|system_user|firebase_id|access)_)?(?:api_)?(?:key|token)$' +
    '|_(?:oauth2?(?:_client(?:_credentials)?)?|login|service_account|handle_password|application_password|basic_auth|account' +
    '|connection_string|server_to_server|bot_install|script|pit|pat|qr|credentials?)$'
);

/** The app a credential type is for, as a person names it: "google_sheets_oauth" → "Google Sheets",
 *  "instagram_login" → "Instagram", "whatsapp_qr" → "WhatsApp". The type is an internal id, never UI text. */
export function credentialLabel(type?: string): string {
  if (!type) return 'account';
  return fixWordCasing(
    type
      .replace(SIGN_IN_SUFFIX, '')
      .split('_')
      .map((w) => (w ? w.charAt(0).toUpperCase() + w.slice(1) : w))
      .join(' ')
  );
}

/** "A", "A and B", "A, B and C". */
function listed(names: string[]): string {
  return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

export interface BridgeAsk {
  /** What the link's preview is titled: "Connect Google Business Profile". */
  title: string;
  /** The page's heading, to the person it asks: "Connect your Google Business Profile". */
  heading: string;
  /** Why, under it: the ask's own reason when it gives one. */
  description: string;
  /** Only accounts to connect, no questions to answer. */
  accountsOnly: boolean;
  /** Its preview's picture: the account it connects, or that it asks questions, or that it's closed. */
  image: string;
}

/** What a link asks, or (`null`: answered, expired, or never a link) that it no longer asks anything. */
export function bridgeAsk(payload: Pick<BridgePayload, 'workflow_name' | 'inputs'> | null): BridgeAsk {
  if (!payload || !payload.inputs.length) {
    return {
      title: 'This link is no longer open',
      heading: 'This link is no longer open',
      description: 'It was answered or has expired. If something still needs you, NoClick will send a new one.',
      accountsOnly: false,
      image: previewImage(CLOSED_ART.key),
    };
  }
  const accounts = [...new Set(payload.inputs.filter((i) => i.type === 'credential').map((i) => credentialLabel(i.credential_type)))];
  const questions = payload.inputs.filter((i) => i.type !== 'credential').length;
  const answer = questions ? `answer ${questions === 1 ? 'a question' : `${questions} questions`}` : '';
  const connect = (whose: string) => (accounts.length ? `Connect ${whose}${listed(accounts)}` : '');
  const sentence = (parts: string[]) => {
    const text = parts.filter(Boolean).join(' and ');
    return text.charAt(0).toUpperCase() + text.slice(1);
  };
  const forWorkflow = accounts.length ? '' : ` for “${payload.workflow_name}”`;
  const reason = payload.inputs.length === 1 ? payload.inputs[0].description?.trim() : undefined;
  return {
    title: sentence([connect(''), answer]) + forWorkflow,
    heading: sentence([connect('your '), answer]) + forWorkflow,
    description: reason || `NoClick needs this to finish “${payload.workflow_name}”.`,
    accountsOnly: !questions,
    image: questions ? previewImage(QUESTION_ART.key) : connectImage(accounts.length === 1 ? accounts[0] : null),
  };
}
