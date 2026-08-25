// Pins the credential-label humanizer: camel-splitting must NOT break
// compound brand names ("WhatsApp" ≠ "Whats App"), acronym runs stay intact,
// and the snake_case path fixes casings Title Case can't know.
import { describe, it, expect } from 'vitest';
import { humanizeCredentialLabel, fixWordCasing } from '~/utils/credentialLabels';

describe('humanizeCredentialLabel', () => {
  it('splits class names into words', () => {
    expect(humanizeCredentialLabel('AccessToken')).toBe('Access Token');
    expect(humanizeCredentialLabel('NotionIntegrationToken')).toBe('Notion Integration Token');
  });

  it('does not break compound brands (the Whats App trap)', () => {
    expect(humanizeCredentialLabel('WhatsAppAccessToken')).toBe('WhatsApp Access Token');
    expect(humanizeCredentialLabel('WhatsAppQR')).toBe('WhatsApp QR');
    expect(humanizeCredentialLabel('GitHubPAT')).toBe('GitHub PAT');
    expect(humanizeCredentialLabel('NotionOAuth')).toBe('Notion OAuth');
    expect(humanizeCredentialLabel('PayPalAPIKey')).toBe('PayPal API Key');
  });

  it('passes already-spaced labels through with casing fixes only', () => {
    expect(humanizeCredentialLabel('Slack Bot Token')).toBe('Slack Bot Token');
    expect(humanizeCredentialLabel('Whatsapp Qr')).toBe('WhatsApp QR');
  });
});

describe('fixWordCasing', () => {
  it('fixes acronyms and brands after naive Title Case', () => {
    expect(fixWordCasing('Whatsapp Qr')).toBe('WhatsApp QR');
    expect(fixWordCasing('Github Api Key')).toBe('GitHub API Key');
  });
});

describe('schema-audit brands (2026-07-19)', () => {
  it('keeps every compound brand from the node schemas intact', () => {
    const cases: Record<string, string> = {
      WordPressApplicationPassword: 'WordPress Application Password',
      WordPressOAuth: 'WordPress OAuth',
      AppSheetApiKey: 'AppSheet API Key',
      ClickHouseApiKey: 'ClickHouse API Key',
      BigQueryServiceAccount: 'BigQuery Service Account',
      SendGridAPIKey: 'SendGrid API Key',
      MongoDB: 'MongoDB',
      OneDriveOAuth: 'OneDrive OAuth',
      PageSpeedApiKey: 'PageSpeed API Key',
      PhantomBusterApiKey: 'PhantomBuster API Key',
      LaunchDarklyToken: 'LaunchDarkly Token',
      GoHighLevelPit: 'GoHighLevel PIT',
      CalComOAuth: 'Cal.com OAuth',
      BlueSkyAppPassword: 'Bluesky App Password',
      RSSFreshRSS: 'RSS FreshRSS',
      SnowflakePat: 'Snowflake PAT',
    };
    for (const [input, want] of Object.entries(cases)) {
      expect(humanizeCredentialLabel(input)).toBe(want);
    }
  });
});
