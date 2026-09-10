// Run with an Instagram node's credential panel open after this release.
// New connections must offer direct login, not the retired Facebook alternative.
import { nc } from '~/lib/nc';

export default async function () {
    const text = document.body.innerText;
    nc.assert.truthy(
        text.includes('Instagram Login'),
        'Direct Instagram Login is visible'
    );
    nc.assert.falsy(
        text.includes('Instagram OAuth'),
        'Legacy Facebook connect is not offered'
    );
    return { directLoginVisible: true, legacyConnectRemoved: true };
}
