// Run with the Instagram credential panel open after this release.
import { nc } from '~/lib/nc';

export default async function () {
    const text = document.body.innerText;
    nc.assert.truthy(text.includes('Instagram Login'), 'Direct Instagram Login is visible');
    nc.assert.truthy(text.includes('Instagram with Facebook Login'), 'Facebook Login is offered for cross-account mentions');
    return { directLoginVisible: true, facebookLoginVisible: true };
}
