// The page's user filter: `?user=` (pages without a query bar) or the `user:`
// token, as the SDK's `userFilter` (the `user_id` query param). It filters
// reads only; writes take an explicit User field (defaultWriteUser).
import { ALL_USERS, NO_USER } from 'noclick';

/** `all`, `none`, or one of your users' ids. */
export type UserFilterValue = string;

/** `?user=` → filter; absent means every user. */
export function parseUserParam(value: string | null | undefined): UserFilterValue {
    return value?.trim() || ALL_USERS;
}

/** The `?user=` value to write; the default (all) drops the param. */
export function userParamValue(filter: UserFilterValue): string | null {
    return filter === ALL_USERS ? null : filter;
}

/** The single user a filter pins, else null. */
export function pinnedUser(filter: UserFilterValue): string | null {
    return filter === ALL_USERS || filter === NO_USER ? null : filter;
}

/** A write form's User field starts at the page filter's user, else your account. */
export function defaultWriteUser(filter: UserFilterValue): string | null {
    return pinnedUser(filter);
}

export function userFilterLabel(filter: UserFilterValue): string {
    if (filter === ALL_USERS) return 'All users';
    if (filter === NO_USER) return 'Your account';
    return filter;
}

/** Who a row belongs to: the user's id, or your account for the account's own. */
export function userLabel(userId: string | null | undefined): string {
    return userId || 'Your account';
}

/** A user's page, relative to the console: the id encoded, since yours may hold `|`, `%` or `#`. */
export function userPath(userId: string): string {
    return `users/${encodeURIComponent(userId)}`;
}
