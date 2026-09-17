// Whether Settings → Phone should exist for this user on this instance:
// linking needs the instance's Twilio Verify service, and the channels a
// verified phone unlocks are rolling out account by account.
import { useInstanceCapabilities } from '~/hooks/useInstanceCapabilities';
import { useFeatureGate } from '~/lib/featureGates';

export function usePhoneLinkingAvailable(): boolean {
    const capabilities = useInstanceCapabilities();
    const rolledOut = useFeatureGate('phone_channel');
    return capabilities.phoneVerification && rolledOut;
}
