// Settings → Developer: building on NoClick from your own code starts in the developer console, which this opens, and
// under it whatever a host kept of the keys made before the console (the older-keys slot).
import { Link } from 'react-router';
import { ArrowRight } from 'lucide-react';
import { useSlot } from '@/slots';
import { BUTTON_PRIMARY } from '@/ui/buttons';
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
