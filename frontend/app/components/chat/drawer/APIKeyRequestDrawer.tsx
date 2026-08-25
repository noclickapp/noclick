// Component for requesting API keys from users when they select AI models
// Shows provider-specific branding and helps users get and save their API keys

import { useState } from 'react';
import { Eye, EyeOff, ExternalLink, Key, X } from 'lucide-react';
import { cn } from '~/lib/utils';
import { ModelProvider, getProviderMetadata, getProviderColors } from '~/types/provider';

interface APIKeyRequestDrawerProps {
    provider: ModelProvider;
    onKeySubmit: (keys: Record<string, string>) => void;
    onClose: () => void;
    initialKeys?: Record<string, string>;
}

// Generate provider configuration from metadata
function getProviderConfig(provider: ModelProvider) {
    const metadata = getProviderMetadata(provider);
    const colors = getProviderColors(provider);
    
    const title = metadata?.title ?? provider;
    const description = `To use ${title} models, you need to provide your API key`;
    
    return {
        title,
        description,
        icon: metadata?.icon,
        primaryColor: colors.primary,
        secondaryColor: colors.secondary || colors.primary,
        accentColor: colors.text,
        descriptionColor: colors.text,
        placeholder: metadata?.requiredApiKeys?.[0]?.[0] || 'API_KEY',
        helpText: `Get your API key from ${title}`,
        helpUrl: metadata?.providerURL,
    };
}

// Helper function to get all unique API key names from requiredApiKeys
function getAllUniqueApiKeys(requiredApiKeys: string[][]): string[] {
    const allKeys = requiredApiKeys.flat();
    return [...new Set(allKeys)];
}

// Helper function to validate if any required key set is complete
function validateApiKeys(apiKeys: Record<string, string>, requiredApiKeys: string[][]): { isValid: boolean; message: string } {
    if (!requiredApiKeys || requiredApiKeys.length === 0) {
        return { isValid: true, message: '' };
    }
    
    // Check if at least one complete set of keys is provided
    const hasCompleteSet = requiredApiKeys.some(keySet => 
        keySet.every(keyName => apiKeys[keyName] && apiKeys[keyName].trim())
    );
    
    if (hasCompleteSet) {
        return { isValid: true, message: '' };
    }
    
    // Generate helpful error message
    if (requiredApiKeys.length === 1) {
        const missingKeys = requiredApiKeys[0].filter(key => !apiKeys[key] || !apiKeys[key].trim());
        return { 
            isValid: false, 
            message: `Please provide: ${missingKeys.join(', ')}` 
        };
    } else {
        const optionMessages = requiredApiKeys.map((keySet, index) => 
            `Option ${index + 1}: ${keySet.join(', ')}`
        ).join(' OR ');
        return { 
            isValid: false, 
            message: `Please provide one complete set: ${optionMessages}` 
        };
    }
}

export function APIKeyRequestDrawer({
    provider,
    onKeySubmit,
    onClose,
    initialKeys
}: APIKeyRequestDrawerProps) {
    const metadata = getProviderMetadata(provider);
    const uniqueApiKeys = getAllUniqueApiKeys(metadata?.requiredApiKeys || []);

    const [apiKeys, setApiKeys] = useState<Record<string, string>>(() =>
        Object.fromEntries(uniqueApiKeys.map(key => [key, initialKeys?.[key] || '']))
    );
    const [showKeys, setShowKeys] = useState<Record<string, boolean>>(() => 
        Object.fromEntries(uniqueApiKeys.map(key => [key, false]))
    );
    const [error, setError] = useState('');
    
    const config = getProviderConfig(provider);
    
    const handleSubmit = async () => {
        // Clear previous error
        setError('');
        
        // Validate API keys using the OR condition logic
        const validation = validateApiKeys(apiKeys, metadata?.requiredApiKeys || []);
        if (!validation.isValid) {
            setError(validation.message);
            return;
        }
        
        // Submit only the keys that have values (trim whitespace)
        const trimmedKeys = Object.fromEntries(
            Object.entries(apiKeys)
                .filter(([, value]) => value.trim())
                .map(([key, value]) => [key, value.trim()])
        );
        
        onKeySubmit(trimmedKeys);
    };
    
    const handleKeyDown = (keyName: string) => (e: React.KeyboardEvent) => {
        if (e.key === 'Enter') {
            // Check if this specific key or a complete set is filled
            const validation = validateApiKeys(apiKeys, metadata?.requiredApiKeys || []);
            if (validation.isValid) {
                handleSubmit();
            }
        } else if (e.key === 'Escape') {
            onClose();
        }
    };
    
    const handleInputChange = (keyName: string) => (e: React.ChangeEvent<HTMLInputElement>) => {
        setApiKeys(prev => ({
            ...prev,
            [keyName]: e.target.value
        }));
    };
    
    const toggleKeyVisibility = (keyName: string) => () => {
        setShowKeys(prev => ({
            ...prev,
            [keyName]: !prev[keyName]
        }));
    };
    
    return (
        <div
            className="flex flex-col w-full overflow-hidden rounded-t-xl"
            style={{
                background: `linear-gradient(to bottom right, ${config.primaryColor}e6, ${config.secondaryColor}33)`
            }}
        >
            {/* Header */}
            <div className="p-4 pb-2 pt-3">
                <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                        <div>{config.icon}</div>
                        <div>
                            <h2 className="text-foreground font-semibold text-lg">{config.title}</h2>
                        </div>
                    </div>
                    <button
                        onClick={onClose}
                        className="text-muted-foreground dark:text-white/60 hover:text-foreground/90 transition-colors"
                        aria-label="Close drawer"
                    >
                        <X className="w-4 h-4" />
                    </button>
                </div>
            </div>
            
            {/* Main content */}
            <div className="px-4 pb-6 space-y-4">
                {/* Description */}
                <p className="text-sm" style={{ color: config.descriptionColor }}>{config.description}</p>
                
                {/* API Key inputs */}
                <div className="space-y-3">
                    {uniqueApiKeys.map((keyName, index) => (
                        <div key={keyName} className="space-y-1">
                            <label className="block text-xs font-medium text-foreground/80">
                                {keyName}
                            </label>
                            <div className="relative">
                                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                    <Key className="h-4 w-4 text-muted-foreground dark:text-zinc-500" />
                                </div>
                                <input
                                    type={showKeys[keyName] ? "text" : "password"}
                                    value={apiKeys[keyName]}
                                    onChange={handleInputChange(keyName)}
                                    onKeyDown={handleKeyDown(keyName)}
                                    placeholder={keyName}
                                    className={cn(
                                        "w-full pl-10 pr-10 py-1.5 bg-card/50 border border-border/50 dark:border-zinc-700/50 rounded-md",
                                        "focus:outline-none focus:ring-2 focus:ring-zinc-600 transition-colors",
                                        "text-foreground placeholder:text-[hsl(var(--placeholder))] text-sm",
                                        error && "border-red-500 focus:ring-red-500/50"
                                    )}
                                    autoFocus={index === 0}
                                />
                                <button
                                    type="button"
                                    onClick={toggleKeyVisibility(keyName)}
                                    className="absolute inset-y-0 right-0 pr-3 flex items-center"
                                >
                                    {showKeys[keyName] ? (
                                        <Eye className="h-4 w-4 text-muted-foreground dark:text-zinc-500 hover:text-foreground/80" />
                                    ) : (
                                        <EyeOff className="h-4 w-4 text-muted-foreground dark:text-zinc-500 hover:text-foreground/80" />
                                    )}
                                </button>
                            </div>
                        </div>
                    ))}
                    
                    {/* OR condition explanation for multiple options */}
                    {metadata?.requiredApiKeys && metadata.requiredApiKeys.length > 1 && (
                        <div className="text-xs text-muted-foreground bg-muted/30 p-2 rounded-md">
                            <strong>Multiple options available:</strong>
                            <ul className="mt-1 space-y-1">
                                {metadata.requiredApiKeys.map((keySet, index) => (
                                    <li key={index} className="flex items-center gap-2">
                                        <span className="text-muted-foreground dark:text-zinc-500">Option {index + 1}:</span>
                                        <span>{keySet.join(' + ')}</span>
                                    </li>
                                ))}
                            </ul>
                            <p className="mt-2 text-muted-foreground dark:text-zinc-500">Provide any one complete option above.</p>
                        </div>
                    )}
                    
                    {error && (
                        <p className="text-red-600 dark:text-red-400 text-sm">{error}</p>
                    )}
                </div>
                
                {/* Help link */}
                <div className="flex items-center justify-between">
                    <a
                        href={config.helpUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-sm hover:underline"
                        style={{ color: config.accentColor }}
                    >
                        <ExternalLink className="w-3 h-3" />
                        {config.helpText}
                    </a>
                </div>
                
            </div>
            
        </div>
    );
}
