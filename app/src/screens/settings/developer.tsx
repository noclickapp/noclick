// Settings → Developer: building on NoClick from your own code starts in the developer console, which this opens, and
// under it whatever a host kept of the keys made before the console (the older-keys slot). `DeveloperSection` opens the
// console at the address of the console context it's drawn in.
import { Link } from 'react-router';
import { ArrowRight } from 'lucide-react';
import { useSlot } from '@/slots';
import { BUTTON_PRIMARY } from '@/ui/buttons';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { SettingsGroup, SettingsHeader, SettingsRow } from './parts';
import { OLDER_KEYS } from './slots';

export function DeveloperView({ consoleHref }: { consoleHref: string }) {
    const OlderKeys = useSlot(OLDER_KEYS);
    return (
        <div>
            <SettingsHeader title="Developer" description="Build on NoClick from your own code." />
            <SettingsGroup>
                <SettingsRow
                    label="Developer console"
                    description="API keys, users, agents, logs and usage."
                    control={
                        <Link to={consoleHref} className={BUTTON_PRIMARY}>
                            Open console
                            <ArrowRight className="h-4 w-4" />
                        </Link>
                    }
                />
            </SettingsGroup>
            {OlderKeys && <OlderKeys />}
        </div>
    );
}

/** The section where the app draws it: the console at its own address. */
export function DeveloperSection() {
    return <DeveloperView consoleHref={useConsole().basePath} />;
}
