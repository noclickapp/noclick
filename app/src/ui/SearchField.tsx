// A page's search: a filled pill with no border, its glyph and placeholder muted, and the shared ✕ while it holds text.
// One look on every page. On a phone it's a finger tall with 16px text (under that, iOS zooms the page into a field as
// it's focused); on a laptop each page keeps the height that suits its row (`size`). Searches inside menus, palettes,
// pickers and dialogs keep their own look.
import { useRef, type ComponentType, type InputHTMLAttributes, type Ref } from 'react';
import { Search } from 'lucide-react';
import { SearchClearButton } from '@/ui/SearchClearButton';
import { cn } from '@/ui/utils';

export type SearchFieldSize = 'sm' | 'md' | 'lg';

const HEIGHT: Record<SearchFieldSize, string> = { sm: 'h-8', md: 'h-9', lg: 'h-10' };
const TEXT: Record<SearchFieldSize, string> = { sm: 'text-[13px]', md: 'text-[13.5px]', lg: 'text-[14px]' };

/** The pill itself, for a box that holds more than one input (a query's chips) or a button that opens a search. */
export function searchFieldClass(size: SearchFieldSize = 'md') {
    return cn(
        'flex min-w-0 items-center gap-2 rounded-full bg-foreground/[0.06] px-3.5 text-muted-foreground transition-colors focus-within:bg-foreground/[0.09] dark:bg-foreground/[0.09] dark:focus-within:bg-foreground/[0.13] max-md:h-10',
        HEIGHT[size]
    );
}

/** Its text: the size its pill takes on a laptop, 16px on a phone. */
export function searchTextClass(size: SearchFieldSize = 'md') {
    return cn(TEXT[size], 'max-md:text-[16px]');
}

type InputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'size' | 'className' | 'placeholder'>;

export function SearchField({
    value,
    onChange,
    placeholder,
    size = 'md',
    icon: Icon = Search,
    clear = true,
    ref,
    className,
    ...input
}: InputProps & {
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
    size?: SearchFieldSize;
    /** Its glyph; null for none (a field that only filters, like digits a number holds). */
    icon?: ComponentType<{ className?: string; strokeWidth?: number; 'aria-hidden'?: boolean }> | null;
    /** Whether the ✕ shows while it holds text. */
    clear?: boolean;
    ref?: Ref<HTMLInputElement>;
    /** For the pill (its width, its margin). */
    className?: string;
}) {
    const own = useRef<HTMLInputElement | null>(null);
    const setRef = (node: HTMLInputElement | null) => {
        own.current = node;
        if (typeof ref === 'function') ref(node);
        else if (ref) ref.current = node;
    };
    return (
        <label className={cn(searchFieldClass(size), clear && value && 'pr-1', className)}>
            {Icon && <Icon aria-hidden className="h-4 w-4 shrink-0" strokeWidth={1.8} />}
            <input
                ref={setRef}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                placeholder={placeholder}
                aria-label={input['aria-label'] ?? placeholder}
                autoComplete="off"
                spellCheck={false}
                enterKeyHint="search"
                {...input}
                className={cn('h-full min-w-0 flex-1 bg-transparent text-foreground outline-none placeholder:text-muted-foreground disabled:opacity-60', searchTextClass(size))}
            />
            {clear && <SearchClearButton value={value} onClear={() => onChange('')} inputRef={own} />}
        </label>
    );
}
