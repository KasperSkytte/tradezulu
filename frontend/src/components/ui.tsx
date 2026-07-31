import clsx from 'clsx'
import { Info, Loader2 } from 'lucide-react'
import { define } from '../lib/glossary'
import type { ButtonHTMLAttributes, ReactNode } from 'react'

export function Card({
  children,
  className,
  padded = true,
}: {
  children: ReactNode
  className?: string
  padded?: boolean
}) {
  return (
    <div className={clsx('tz-card', padded && 'p-4 sm:p-5', className)}>{children}</div>
  )
}

export function CardHeader({
  title,
  hint,
  action,
  className,
}: {
  title: ReactNode
  hint?: string
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={clsx('mb-4 flex items-start justify-between gap-3', className)}>
      <div className="flex items-center gap-1.5">
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        {(hint ?? (typeof title === 'string' ? define(title) : undefined)) && (
          <Hint text={hint ?? define(String(title))!} />
        )}
      </div>
      {action}
    </div>
  )
}

/**
 * An explanation on hover, and on keyboard focus.
 *
 * This used to be the native `title` attribute, which on most systems shows
 * nothing but a changed cursor unless you hover for a second and a half — so
 * the explanations were written and then effectively invisible. This draws its
 * own, immediately.
 *
 * `group` plus `peer` rather than React state: no re-render, and it works the
 * same for a mouse and for a tab key.
 */
export function Hint({ text, className }: { text: string; className?: string }) {
  return (
    <span className={clsx('relative inline-flex', className)}>
      <button
        type="button"
        aria-label={text}
        // Explanations are read-only, so this never needs to be activated --
        // but it must be focusable, or the text is mouse-only.
        onClick={(event) => event.preventDefault()}
        className="peer inline-flex cursor-help rounded-full text-[var(--tz-text-faint)] outline-none transition-colors hover:text-[var(--tz-text-muted)] focus-visible:text-[var(--tz-text-muted)] focus-visible:ring-1 focus-visible:ring-[var(--tz-accent)]"
      >
        <Info size={13} strokeWidth={2} />
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 w-64 -translate-x-1/2 rounded-md border border-[var(--tz-border)] bg-[var(--tz-surface-1)] px-2.5 py-2 text-xs font-normal leading-snug text-[var(--tz-text)] opacity-0 shadow-lg transition-opacity duration-100 peer-hover:opacity-100 peer-focus-visible:opacity-100"
      >
        {text}
      </span>
    </span>
  )
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'ghost' | 'danger'
  loading?: boolean
  icon?: ReactNode
}

export function Button({
  variant = 'ghost',
  loading = false,
  icon,
  children,
  className,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      className={clsx(
        'tz-btn',
        variant === 'primary' && 'tz-btn-primary',
        variant === 'ghost' && 'tz-btn-ghost',
        variant === 'danger' && 'tz-btn-danger',
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 size={15} className="animate-spin" /> : icon}
      {children}
    </button>
  )
}

export function Chip({
  children,
  color,
  className,
}: {
  children: ReactNode
  color?: string
  className?: string
}) {
  return (
    <span
      className={clsx('tz-chip', className)}
      style={
        color
          ? {
              backgroundColor: `color-mix(in srgb, ${color} 18%, transparent)`,
              color,
              border: `1px solid color-mix(in srgb, ${color} 35%, transparent)`,
            }
          : undefined
      }
    >
      {children}
    </span>
  )
}

export function OutcomeBadge({ outcome }: { outcome: string }) {
  const map: Record<string, { label: string; color: string }> = {
    win: { label: 'Win', color: 'var(--color-gain-500)' },
    loss: { label: 'Loss', color: 'var(--color-loss-500)' },
      // Its own colour, not the grey used for "no data": a breakeven is a
      // result, and one worth seeing at a glance among wins and losses.
      breakeven: { label: 'Breakeven', color: 'var(--tz-breakeven)' },
    open: { label: 'Open', color: 'var(--color-zulu-400)' },
  }
  const entry = map[outcome] ?? map.open
  return <Chip color={entry.color}>{entry.label}</Chip>
}

export function DirectionBadge({ direction }: { direction: string }) {
  const long = direction === 'long'
  return (
    <span
      className={clsx(
        'tz-chip font-semibold uppercase tracking-wide',
        long ? 'text-gain-500' : 'text-loss-500',
      )}
      style={{
        backgroundColor: long
          ? 'color-mix(in srgb, var(--color-gain-500) 14%, transparent)'
          : 'color-mix(in srgb, var(--color-loss-500) 14%, transparent)',
      }}
    >
      {long ? 'Long' : 'Short'}
    </span>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('tz-skeleton', className)} />
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode
  title: string
  description?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      {icon && <div className="text-[var(--tz-text-faint)]">{icon}</div>}
      <div>
        <p className="font-medium">{title}</p>
        {description && (
          <p className="mt-1 max-w-md text-sm text-[var(--tz-text-muted)]">{description}</p>
        )}
      </div>
      {action}
    </div>
  )
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Something went wrong'
  return (
    <EmptyState
      title="Could not load this"
      description={message}
      action={
        retry ? (
          <Button onClick={retry} variant="ghost">
            Try again
          </Button>
        ) : undefined
      }
    />
  )
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  label: string
  description?: string
  disabled?: boolean
}) {
  return (
    <label
      className={clsx(
        'flex items-start justify-between gap-4 py-2',
        disabled && 'cursor-not-allowed opacity-60',
      )}
    >
      <span className="min-w-0">
        <span className="block text-sm font-medium">{label}</span>
        {description && (
          <span className="mt-0.5 block text-xs text-[var(--tz-text-muted)]">{description}</span>
        )}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={clsx(
          'relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors',
          checked ? 'bg-zulu-500' : 'bg-[var(--tz-border-strong)]',
        )}
      >
        <span
          className={clsx(
            'absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform',
            checked ? 'translate-x-4.5' : 'translate-x-0.5',
          )}
        />
      </button>
    </label>
  )
}

export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string
  hint?: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={className}>
      <div className="flex items-center gap-1.5">
        <span className="tz-label">{label}</span>
        {/* An explicit hint wins; otherwise the glossary answers for the
            label, so a term like "Kelly fraction" is explained wherever it
            appears rather than only where somebody remembered. */}
        {(hint ?? define(label)) && (
          <span className="mb-1.5">
            <Hint text={hint ?? define(label)!} />
          </span>
        )}
      </div>
      {children}
    </div>
  )
}

export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  size = 'md',
}: {
  value: T
  options: { value: T; label: ReactNode; title?: string }[]
  onChange: (value: T) => void
  size?: 'sm' | 'md'
}) {
  return (
    <div className="inline-flex rounded-lg border border-[var(--tz-border)] bg-[var(--tz-surface-2)] p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          title={option.title}
          onClick={() => onChange(option.value)}
          className={clsx(
            'rounded-[6px] font-medium transition-colors',
            size === 'sm' ? 'px-2 py-1 text-xs' : 'px-3 py-1.5 text-sm',
            value === option.value
              ? 'bg-[var(--tz-surface)] text-[var(--tz-text)] shadow-sm'
              : 'text-[var(--tz-text-muted)] hover:text-[var(--tz-text)]',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

export function Progress({ value, color }: { value: number; color?: string }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--tz-border)]">
      <div
        className="h-full rounded-full transition-[width] duration-500"
        style={{
          width: `${Math.max(0, Math.min(100, value))}%`,
          backgroundColor: color ?? 'var(--color-zulu-500)',
        }}
      />
    </div>
  )
}
