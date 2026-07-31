/**
 * Add several tags to several trades at once.
 *
 * The old control was a single dropdown that applied one tag and closed, so
 * tagging a batch "FOMO, late entry, news" meant three passes over the same
 * selection. This keeps the menu open, takes as many as you want, and sends
 * them in one request — the API already accepted a list.
 *
 * Tags are grouped by what they are for. A flat alphabetical list mixes "Broke
 * my rules" in with "London open", which are not the same kind of thing and are
 * never being looked for at the same moment.
 */

import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Tags } from 'lucide-react'
import clsx from 'clsx'
import type { Tag } from '../lib/types'
import { Button } from './ui'

/** Order matters: this is the order they appear in the menu. */
const SECTIONS: { key: Tag['category']; label: string }[] = [
  { key: 'setup', label: 'Setup' },
  { key: 'mistake', label: 'Mistakes' },
  { key: 'emotion', label: 'Behaviour' },
  { key: 'custom', label: 'Other' },
]

export function BulkTagMenu({
  tags,
  onApply,
  pending,
}: {
  tags: Tag[]
  onApply: (tagIds: number[]) => void
  pending?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [chosen, setChosen] = useState<Set<number>>(new Set())
  const box = useRef<HTMLDivElement>(null)

  // Close on a click elsewhere or on Escape. Without this the menu covers the
  // table it is about and there is no obvious way out of it.
  useEffect(() => {
    if (!open) return
    const away = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false)
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', escape)
    }
  }, [open])

  const toggle = (id: number) =>
    setChosen((previous) => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const apply = () => {
    if (chosen.size === 0) return
    onApply([...chosen])
    setChosen(new Set())
    setOpen(false)
  }

  // Sections with nothing in them are not shown: an empty "Mistake" heading
  // reads as something failing to load.
  const sections = SECTIONS.map((section) => ({
    ...section,
    items: tags.filter((tag) => tag.category === section.key),
  })).filter((section) => section.items.length > 0)

  return (
    <div className="relative" ref={box}>
      <Button
        icon={<Tags size={15} />}
        onClick={() => setOpen((value) => !value)}
        loading={pending}
      >
        Add tags
        {chosen.size > 0 && (
          <span className="ml-1 rounded-full bg-zulu-500/20 px-1.5 text-xs">{chosen.size}</span>
        )}
        <ChevronDown size={14} className={clsx('transition-transform', open && 'rotate-180')} />
      </Button>

      {open && (
        <div className="tz-fade-in absolute left-0 top-full z-50 mt-1 max-h-80 w-64 overflow-y-auto rounded-lg border border-[var(--tz-border)] bg-[var(--tz-surface-1)] p-1.5 shadow-lg">
          {sections.length === 0 && (
            <p className="px-2 py-3 text-sm text-[var(--tz-text-muted)]">
              No tags yet — add some under Settings.
            </p>
          )}

          {sections.map((section) => (
            <div key={section.key} className="mb-1 last:mb-0">
              <p className="px-2 pb-0.5 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--tz-text-faint)]">
                {section.label}
              </p>
              {section.items.map((tag) => {
                const on = chosen.has(tag.id)
                return (
                  <button
                    key={tag.id}
                    type="button"
                    onClick={() => toggle(tag.id)}
                    className={clsx(
                      'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors',
                      on
                        ? 'bg-zulu-500/12 text-[var(--tz-text)]'
                        : 'text-[var(--tz-text-muted)] hover:bg-[var(--tz-surface-2)]',
                    )}
                  >
                    <span
                      className={clsx(
                        'flex size-4 shrink-0 items-center justify-center rounded border',
                        on
                          ? 'border-transparent bg-[var(--tz-accent)] text-white'
                          : 'border-[var(--tz-border)]',
                      )}
                    >
                      {on && <Check size={11} strokeWidth={3} />}
                    </span>
                    <span className="truncate">{tag.name}</span>
                  </button>
                )
              })}
            </div>
          ))}

          {sections.length > 0 && (
            <div className="mt-1.5 flex items-center gap-2 border-t border-[var(--tz-border)] pt-1.5">
              <Button
                variant="primary"
                className="flex-1"
                disabled={chosen.size === 0}
                onClick={apply}
              >
                Apply{chosen.size > 0 ? ` ${chosen.size}` : ''}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
