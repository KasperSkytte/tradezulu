import {
  endOfMonth,
  endOfQuarter,
  endOfWeek,
  endOfYear,
  startOfMonth,
  startOfQuarter,
  startOfWeek,
  startOfYear,
  subDays,
  subMonths,
  subWeeks,
  subYears,
} from 'date-fns'
import { isoDate } from './format'

export interface PeriodOption {
  id: string
  label: string
  group: 'recent' | 'calendar' | 'other'
}

export const PERIOD_OPTIONS: PeriodOption[] = [
  { id: 'today', label: 'Today', group: 'recent' },
  { id: 'yesterday', label: 'Yesterday', group: 'recent' },
  { id: 'last_7_days', label: 'Last 7 days', group: 'recent' },
  { id: 'last_30_days', label: 'Last 30 days', group: 'recent' },
  { id: 'last_90_days', label: 'Last 90 days', group: 'recent' },
  { id: 'last_180_days', label: 'Last 180 days', group: 'recent' },
  { id: 'this_week', label: 'This week', group: 'calendar' },
  { id: 'last_week', label: 'Last week', group: 'calendar' },
  { id: 'this_month', label: 'This month', group: 'calendar' },
  { id: 'last_month', label: 'Last month', group: 'calendar' },
  { id: 'this_quarter', label: 'This quarter', group: 'calendar' },
  { id: 'this_year', label: 'This year', group: 'calendar' },
  { id: 'last_year', label: 'Last year', group: 'calendar' },
  { id: 'all', label: 'All time', group: 'other' },
]

export interface Range {
  start: string
  end: string
}

/** Mirror of the server-side period presets so the picker can show real dates. */
export function resolvePeriod(id: string, weekStartsOn: 0 | 1 = 1, today = new Date()): Range {
  const day = (d: Date) => isoDate(d)
  switch (id) {
    case 'today':
      return { start: day(today), end: day(today) }
    case 'yesterday': {
      const d = subDays(today, 1)
      return { start: day(d), end: day(d) }
    }
    case 'last_7_days':
      return { start: day(subDays(today, 6)), end: day(today) }
    case 'last_30_days':
      return { start: day(subDays(today, 29)), end: day(today) }
    case 'last_90_days':
      return { start: day(subDays(today, 89)), end: day(today) }
    case 'last_180_days':
      return { start: day(subDays(today, 179)), end: day(today) }
    // The calendar presets run to the end of the period they name, not to
    // today: "this week" ending on Wednesday is not this week, and the days
    // still to come were missing from the calendar because of it.
    case 'this_week':
      return {
        start: day(startOfWeek(today, { weekStartsOn })),
        end: day(endOfWeek(today, { weekStartsOn })),
      }
    case 'last_week': {
      const ref = subWeeks(today, 1)
      return {
        start: day(startOfWeek(ref, { weekStartsOn })),
        end: day(endOfWeek(ref, { weekStartsOn })),
      }
    }
    case 'this_month':
      return { start: day(startOfMonth(today)), end: day(endOfMonth(today)) }
    case 'last_month': {
      const ref = subMonths(today, 1)
      return { start: day(startOfMonth(ref)), end: day(endOfMonth(ref)) }
    }
    case 'this_quarter':
      return { start: day(startOfQuarter(today)), end: day(endOfQuarter(today)) }
    case 'this_year':
      return { start: day(startOfYear(today)), end: day(endOfYear(today)) }
    case 'last_year': {
      const ref = subYears(today, 1)
      return { start: day(startOfYear(ref)), end: day(endOfYear(ref)) }
    }
    case 'all':
      return { start: '1970-01-01', end: day(today) }
    default:
      return { start: day(subDays(today, 29)), end: day(today) }
  }
}

export function periodLabel(id: string): string {
  return PERIOD_OPTIONS.find((option) => option.id === id)?.label ?? 'Custom range'
}
