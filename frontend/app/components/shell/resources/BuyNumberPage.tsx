// Buying a phone number by hand, as a page one level under Numbers: it opens on numbers for sale in the person's own
// country, narrowed by kind, place, digits and whether it takes texts, each at its own price; buying asks once, in place,
// with what's charged now, and a country that asks for the holder's address, or for documents, gets them as a step of
// its own. A number bought with documents stays here, in review, until the carrier approves them. The same purchase
// flow the Phone node's form, the chat's card and the console use.
import { toast } from 'sonner';
import type { OAuthExchange } from '~/hooks/oauth/OAuthExchangeContext';
import { NumberFinder } from '~/components/phone/NumberFinder';
import { formatNumber } from '~/components/phone/numberDisplay';
import { usePhoneNumberPurchase } from '~/hooks/usePhoneNumberPurchase';
import { PageFrame } from '../PageFrame';
import { Section, Surface } from './ui';

export function BuyNumberPage({ onBack, onBought, sendEvent }: { onBack: () => void; onBought: () => void; /** Transport override, for tests. */ sendEvent?: OAuthExchange }) {
    const purchase = usePhoneNumberPurchase({
        sendEvent,
        onCredentialCreated: (_credentialId, phoneNumber) => {
            toast.success(`${formatNumber(phoneNumber)} is yours`);
            onBought();
        },
        onOrdered: ({ phone_number }) => toast.success(`${formatNumber(phone_number)} is in the carrier’s review. You’ll get an email when it’s done.`),
    });
    return (
        <PageFrame
            title="Buy a number"
            description="A number your agents answer calls on and call out from, in any country numbers are sold in, each at its own price."
            back={{ label: 'Numbers', onBack }}
        >
            <NumberFinder
                purchase={purchase}
                list={(rows) => (
                    <Section title="Available" meta={purchase.numbers?.length || undefined} className="mt-2">
                        <Surface>{rows}</Surface>
                    </Section>
                )}
            />
        </PageFrame>
    );
}
