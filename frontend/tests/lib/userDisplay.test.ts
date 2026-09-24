import { describe, expect, it } from 'vitest';
import { userDisplayName, userInitials } from '~/lib/userDisplay';

describe('userDisplay', () => {
  it('prefers the name, then the email, for an email account', () => {
    expect(userDisplayName({ full_name: 'Ada Lovelace', email: 'ada@example.com' })).toBe('Ada Lovelace');
    expect(userDisplayName({ email: 'ada@example.com' })).toBe('ada');
    expect(userInitials({ full_name: 'Ada Lovelace', email: 'ada@example.com' })).toBe('AD');
  });

  it('never reads a missing email on a phone-only account', () => {
    expect(userDisplayName({ username: 'Priya', email: null })).toBe('Priya');
    expect(userDisplayName({ email: '', phone: '12066368280' })).toBe('+1 206 636 8280');
    expect(userDisplayName({ email: null }, '')).toBe('');
    expect(userInitials({ username: 'Priya', email: null })).toBe('PR');
    expect(userInitials({ email: null })).toBe('?');
  });
});
