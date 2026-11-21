// The pages on NoClick's own site that the console links to, each built on the `site` its host hands it
// (`ConsoleContextValue.site`: an origin such as `https://noclick.com`, or empty where the console is served from that
// site itself). This is the one list of them, so a console served elsewhere never links to a page it doesn't have.

/** NoClick's own site, for a console served anywhere else. */
export const NOCLICK_SITE = 'https://noclick.com';

/** A docs page: `docsUrl(site, 'guide/agents')`. */
export const docsUrl = (site: string, page = 'guide') => `${site}/docs/${page}`;

/** The docs' front doors, in the order Settings lists them. */
export function docsLinks(site: string): readonly { id: string; title: string; href: string }[] {
    return [
        { id: 'guide', title: 'Guide', href: docsUrl(site) },
        { id: 'python', title: 'Python reference', href: docsUrl(site, 'reference/python') },
        { id: 'typescript', title: 'TypeScript client', href: docsUrl(site, 'reference/typescript') },
    ];
}

/** A page of NoClick's own developer console, where a person signed in to NoClick does what a key can't. `search` is
 *  a query to carry over (`?code=…`). */
export const noclickConsoleUrl = (site: string, page: string, search = '') => `${site}/dashboard/developers/${page}${search}`;

/** The plans and what each service costs. */
export const pricingUrl = (site: string) => `${site}/pricing`;

/** Where funds are added: where a `payment_required` error's next step also sends you. */
export const addFundsUrl = (site: string) => `${site}/dashboard?action=topup`;

/** A call held for the owner's yes, on the page that approves it (the owner signs in there, or opens the link NoClick
 *  sends them). */
export const approvalUrl = (site: string, approvalId: string) => `${site}/approve/${encodeURIComponent(approvalId)}`;

/** The account's plan, balance and monthly cap, on Settings → Plan and billing in the NoClick app. */
export const billingSettingsUrl = (site: string) => `${site}/dashboard?tab=settings&section=billing`;

/** Where the owner links their phone, so a text from it reaches their own account (Settings → Phone). */
export const phoneSettingsUrl = (site: string) => `${site}/dashboard?tab=settings&section=phone`;

/** An account connected in the NoClick app, on its page under Connections (who may use it, and more). */
export const connectionUrl = (site: string, accountId: string) => `${site}/dashboard?tab=connections&view=connected&account=${encodeURIComponent(accountId)}`;

/** Which of a connected account's actions wait for its owner's OK, on its page in the NoClick app. */
export const accountApprovalsUrl = (site: string, accountId: string) => `${site}/credential/permissions/${encodeURIComponent(accountId)}`;

/** An automation on its canvas in the NoClick app. */
export const workflowUrl = (site: string, workflowId: string) => `${site}/dashboard?workflow=${encodeURIComponent(workflowId)}`;

/** The older workflow SDK's keys, on Settings → Developer in the NoClick app. */
export const legacyKeysUrl = (site: string) => `${site}/dashboard?tab=settings&section=developer`;

/** The machines usage policy: section 3 of the Acceptable Use Policy. */
export const machinesPolicyUrl = (site: string) => `${site}/legal/acceptable-use#3-sandboxes-machines-and-other-compute`;
