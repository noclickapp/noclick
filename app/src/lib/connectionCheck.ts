// What a provider said when asked about one connected account (its channels, its repositories, who it signs in as),
// and the verdict that answer makes. Attached is not working: only the provider's own answer says an account works.

/** The provider's answer about an account. */
export interface ConnectionCheck {
    /** True: the provider answered. False: it turned the account down. Null: there's no telling. */
    reachable?: boolean | null;
    /** Recognisable things of the account's, as the provider sees them. */
    samples?: { label: string; value?: string | null }[];
    /** The account's word for those things ("repositories", "channels"). */
    noun?: string;
    /** How many there were, when more than the samples. */
    total?: number | null;
    /** Who the account signs in as. */
    account_label?: string | null;
    /** `reachability` when the provider has nothing of the account's own to show: it only accepted the key. */
    proves?: string;
    /** The setting the samples can fill (a step's channel, picked from the account's own); null where they answer
     *  none. */
    answers_field?: string | null;
    /** The provider's own words when it turned the account down. */
    error?: string | null;
    /** What to do about a refusal, in NoClick's words. */
    hint?: string | null;
}

export type CheckVerdict = 'working' | 'rejected' | 'unverified';

/** Working only when the provider answered, rejected only when it refused; anything else says nothing either way. */
export function checkVerdict(check: Pick<ConnectionCheck, 'reachable'> | null | undefined): CheckVerdict {
    if (check?.reachable === true) return 'working';
    if (check?.reachable === false) return 'rejected';
    return 'unverified';
}
