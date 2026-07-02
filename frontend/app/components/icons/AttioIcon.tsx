// Attio logo icon component.
// Renders the Attio brand mark from /icons/attio.svg (react-icons has no SiAttio).
// Added so the OAuth provider config can reference an Attio icon like other providers.

import { ImgHTMLAttributes } from 'react';

export function AttioIcon(props: ImgHTMLAttributes<HTMLImageElement>) {
    return <img src="/icons/attio.svg" alt="" {...props} />;
}
