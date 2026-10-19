// Which calls answered with a phone number's purchase page. Apart from PurchaseCards so a platform can recognise one
// (cloud/bootstrap, on every page) without loading the card.
import { failed, str, type CoordinatorToolCall } from '~/lib/coordinatorToolCalls';

/** The purchase page a call answered with, where the person picks the number: its token. */
export function purchaseToken(call: CoordinatorToolCall): string | undefined {
    const approval = str(call.result, 'approval_url');
    return approval ? /\/credential\/purchase\/([^/?#]+)/.exec(approval)?.[1] : undefined;
}

/** A call, whatever its tool, that answered with a phone number's purchase page (hosted: a platform quote for a
 * number whose country asks for documents, which the person gives there). */
export function isPhonePurchaseLink(call: CoordinatorToolCall): boolean {
    return !failed(call.result) && !!purchaseToken(call);
}
