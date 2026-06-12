/**
 * Date Range Picker Component
 *
 * A date range picker with confirmation dialog that prevents premature data fetching.
 * Features Apply/Cancel buttons and improved visual feedback for range selection.
 */

import { useState, useEffect } from 'react';
import { Calendar as CalendarIcon } from 'lucide-react';
import { DateRange } from 'react-day-picker';
import { format } from 'date-fns';

import { cn } from '~/lib/utils';
import { Button } from '~/components/ui/button';
import { Calendar } from '~/components/ui/calendar';
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from '~/components/ui/popover';

interface DateRangePickerProps {
    dateRange: DateRange | undefined;
    onDateRangeChange: (range: DateRange | undefined) => void;
    className?: string;
    align?: 'start' | 'center' | 'end';
}

export function DateRangePicker({
    dateRange,
    onDateRangeChange,
    className,
    align = 'start',
}: DateRangePickerProps) {
    const [isOpen, setIsOpen] = useState(false);
    const [tempDateRange, setTempDateRange] = useState<DateRange | undefined>(
        dateRange
    );
    const [isMobile, setIsMobile] = useState(false);

    useEffect(() => {
        const check = () => setIsMobile(window.innerWidth < 640);
        check();
        window.addEventListener('resize', check);
        return () => window.removeEventListener('resize', check);
    }, []);

    // Reset temp range when popover opens
    const handleOpenChange = (open: boolean) => {
        setIsOpen(open);
        if (open) {
            setTempDateRange(dateRange);
        } else {
            // Auto-apply when clicking outside (popover closes)
            if (tempDateRange?.from && tempDateRange?.to) {
                onDateRangeChange(tempDateRange);
            }
        }
    };

    // Format date range for display
    const formatDateRange = (range: DateRange | undefined) => {
        if (!range?.from) return 'Pick a date range';
        if (!range.to) return format(range.from, 'MMM dd, yyyy');
        return `${format(range.from, 'MMM dd, yyyy')} - ${format(range.to, 'MMM dd, yyyy')}`;
    };

    return (
        <div className={cn('flex', className)}>
            <Popover open={isOpen} onOpenChange={handleOpenChange}>
                <PopoverTrigger asChild>
                    <Button
                        variant={'outline'}
                        className={cn(
                            // Settings-surface palette (matches credentials/published-apps controls)
                            'h-8 sm:h-9 px-3 justify-start text-left font-normal text-xs bg-secondary text-muted-foreground hover:bg-accent hover:text-foreground border-border whitespace-nowrap',
                            isMobile && 'flex-1 min-w-0',
                            !dateRange && 'text-muted-foreground'
                        )}
                    >
                        <CalendarIcon className="mr-2 h-3.5 w-3.5 flex-shrink-0" />
                        {formatDateRange(dateRange)}
                    </Button>
                </PopoverTrigger>
                <PopoverContent
                    className="p-0 w-auto bg-card border-border shadow-xl rounded-xl"
                    align={isMobile ? 'end' : align}
                    sideOffset={8}
                    collisionPadding={{ top: 8, right: 8, bottom: 8, left: 8 }}
                >
                    <div className="flex flex-col">
                        {/* Date Range Display Header */}
                        {tempDateRange?.from && (
                            <div className="px-4 pt-3 pb-2.5 border-b border-border">
                                <div className="flex items-center justify-center gap-2 text-xs sm:text-sm">
                                    <span className="text-foreground/80 font-medium">
                                        {format(
                                            tempDateRange.from,
                                            'MMM dd, yyyy'
                                        )}
                                    </span>
                                    {tempDateRange.to && (
                                        <>
                                            <span className="text-muted-foreground/70">
                                                —
                                            </span>
                                            <span className="text-foreground/80 font-medium">
                                                {format(
                                                    tempDateRange.to,
                                                    'MMM dd, yyyy'
                                                )}
                                            </span>
                                        </>
                                    )}
                                </div>
                            </div>
                        )}

                        {/* Calendar — 1 month on mobile, 2 on desktop */}
                        <Calendar
                            mode="range"
                            defaultMonth={tempDateRange?.from}
                            selected={tempDateRange}
                            onSelect={setTempDateRange}
                            numberOfMonths={isMobile ? 1 : 2}
                            className="bg-transparent text-foreground"
                        />
                    </div>
                </PopoverContent>
            </Popover>
        </div>
    );
}
