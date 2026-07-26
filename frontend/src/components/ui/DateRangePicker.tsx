import { CalendarDays } from 'lucide-react'

export interface DateRange {
  from: string  // ISO date string YYYY-MM-DD
  to: string
}

interface Props {
  value: DateRange
  onChange: (range: DateRange) => void
  className?: string
}

export function DateRangePicker({ value, onChange, className = '' }: Props) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <CalendarDays size={15} className="text-t3 shrink-0" />
      <input
        type="date"
        className="input py-1 text-xs w-36"
        value={value.from}
        max={value.to || undefined}
        onChange={(e) => onChange({ ...value, from: e.target.value })}
      />
      <span className="text-t3 text-xs">–</span>
      <input
        type="date"
        className="input py-1 text-xs w-36"
        value={value.to}
        min={value.from || undefined}
        onChange={(e) => onChange({ ...value, to: e.target.value })}
      />
    </div>
  )
}
