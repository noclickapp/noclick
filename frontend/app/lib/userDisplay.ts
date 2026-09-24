// A phone-only account (made by a WhatsApp first contact) has no email, so a
// user's label is never derived from the email alone.
import { formatPhoneForDisplay } from '~/lib/phoneFormat';

export interface UserIdentity {
  full_name?: string | null;
  name?: string | null;
  username?: string | null;
  email?: string | null;
  phone?: string | null;
}

/** Name, else the email's local part, else the formatted phone. */
export function userDisplayName(user: UserIdentity, fallback = 'Unknown'): string {
  return (
    user.full_name ||
    user.name ||
    user.username ||
    user.email?.split('@')[0] ||
    (user.phone ? formatPhoneForDisplay(user.phone) : '') ||
    fallback
  );
}

/** Two-letter avatar initials: from the email when there is one, else the label. */
export function userInitials(user: UserIdentity): string {
  return (user.email || userDisplayName(user, '?')).replace(/^\+/, '').slice(0, 2).toUpperCase();
}
