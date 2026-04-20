// Shared empty state for tabs that require a selected node. Each tab just
// passes its own descriptor ("configuration", "credentials", etc.).
export function TabEmptyState({ message }: { message: string }) {
    return (
        <div className="flex items-center justify-center h-full">
            <div className="text-center text-zinc-500 text-sm">{message}</div>
        </div>
    );
}
