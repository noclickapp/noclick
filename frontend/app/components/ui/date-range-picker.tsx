/**
 * Date Range Picker Component
 *
 * A date range picker with confirmation dialog that prevents premature data fetching.
 * Features Apply/Cancel buttons and improved visual feedback for range selection.
 */

import { useState } from "react"
import { Calendar as CalendarIcon } from "lucide-react"
import { DateRange } from "react-day-picker"
import { format } from "date-fns"

import { cn } from "~/lib/utils"
import { Button } from "~/components/ui/button"
import { Calendar } from "~/components/ui/calendar"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "~/components/ui/popover"

interface DateRangePickerProps {
  dateRange: DateRange | undefined
  onDateRangeChange: (range: DateRange | undefined) => void
  className?: string
  align?: "start" | "center" | "end"
}

export function DateRangePicker({
  dateRange,
  onDateRangeChange,
  className,
  align = "start",
}: DateRangePickerProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [tempDateRange, setTempDateRange] = useState<DateRange | undefined>(dateRange)

  // Reset temp range when popover opens
  const handleOpenChange = (open: boolean) => {
    setIsOpen(open)
    if (open) {
      setTempDateRange(dateRange)
    }
  }

  // Apply the selected range
  const handleApply = () => {
    if (tempDateRange?.from && tempDateRange?.to) {
      onDateRangeChange(tempDateRange)
      setIsOpen(false)
    }
  }

  // Cancel and reset
  const handleCancel = () => {
    setTempDateRange(dateRange)
    setIsOpen(false)
  }

  // Format date range for display
  const formatDateRange = (range: DateRange | undefined) => {
    if (!range?.from) return "Pick a date range"
    if (!range.to) return format(range.from, "MMM dd, yyyy")
    return `${format(range.from, "MMM dd, yyyy")} - ${format(range.to, "MMM dd, yyyy")}`
  }

  return (
    <div className={cn("grid gap-2", className)}>
      <Popover open={isOpen} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          <Button
            variant={"outline"}
            className={cn(
              "h-9 px-3 justify-start text-left font-normal text-xs bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-100 border-zinc-700 whitespace-nowrap",
              !dateRange && "text-zinc-500"
            )}
          >
            <CalendarIcon className="mr-2 h-3.5 w-3.5 flex-shrink-0" />
            {formatDateRange(dateRange)}
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className="w-auto p-0 bg-zinc-900 border-zinc-700 shadow-xl rounded-lg"
          align={align}
          sideOffset={8}
        >
          <div className="flex flex-col">
            {/* Date Range Display Header */}
            {tempDateRange?.from && (
              <div className="px-4 pt-4 pb-3 border-b border-zinc-800">
                <div className="flex items-center justify-center gap-2 text-sm">
                  <span className="text-zinc-400">
                    {format(tempDateRange.from, "MMM dd, yyyy")}
                  </span>
                  {tempDateRange.to && (
                    <>
                      <span className="text-zinc-600">—</span>
                      <span className="text-zinc-400">
                        {format(tempDateRange.to, "MMM dd, yyyy")}
                      </span>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* Calendar */}
            <Calendar
              mode="range"
              defaultMonth={tempDateRange?.from}
              selected={tempDateRange}
              onSelect={setTempDateRange}
              numberOfMonths={1}
              className="bg-zinc-900 text-zinc-100"
            />

            {/* Action Buttons */}
            <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-zinc-800">
              <Button
                variant="ghost"
                size="sm"
                onClick={handleCancel}
                className="h-9 px-4 text-xs text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800"
              >
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={handleApply}
                disabled={!tempDateRange?.from || !tempDateRange?.to}
                className="h-9 px-4 text-xs bg-zinc-900 hover:bg-zinc-800 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Apply
              </Button>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  )
}

