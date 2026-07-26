import clsx from 'clsx'
import { Info, Loader2 } from 'lucide-react'
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
        {hint && <Hint text={hint} />}
      </div>
      {action}
    </div>
  )
}

export function Hint({ text }: { text: string }) {
  return (
    <span
      title={text}
      className="inline-flex cursor-help text-[var(--tz-text-faint)] transition-colors hover:text-[var(--tz-text-muted)]"
    >
      <Info size={13} strokeWidth={2} />
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
    breakeven: { label: 'Breakeven', color: 'var(--color-flat-400)' },
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
        {hint && <span className="mb-1.5"><Hint text={hint} /></span>}
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
