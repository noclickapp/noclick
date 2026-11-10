// Attio logo icon component.
// Renders the Attio brand mark from /icons/attio.svg (react-icons has no SiAttio), black in light mode.
// Added so the OAuth provider config can reference an Attio icon like other providers.

import { ImgHTMLAttributes } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

export function AttioIcon(props: ImgHTMLAttributes<HTMLImageElement>) {
    return <ThemedBrandImg {...props} light="/icons/attio-light.svg" dark="/icons/attio.svg" />;
}
