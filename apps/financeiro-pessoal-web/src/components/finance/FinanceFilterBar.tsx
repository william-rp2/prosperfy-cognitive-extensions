import { useMemo, useState } from 'react'

import { Input } from '../ui/input'

export interface FilterOption {
  value: string
  label: string
}

export function SearchableSelect({
  label,
  value,
  options,
  onChange,
  placeholder = 'Selecionar…',
}: {
  label: string
  value: string
  options: FilterOption[]
  onChange: (value: string) => void
  placeholder?: string
}) {
  const [query, setQuery] = useState('')
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options.slice(0, 40)
    return options.filter(opt => opt.label.toLowerCase().includes(q)).slice(0, 40)
  }, [options, query])

  return (
    <label className="block text-xs font-semibold text-[#76677d]">
      {label}
      <Input
        aria-label={`${label} busca`}
        className="mt-1 mb-1"
        onChange={event => setQuery(event.target.value)}
        placeholder="Filtrar opções…"
        value={query}
      />
      <select
        aria-label={label}
        className="w-full rounded-xl border border-[#eadfec] bg-white px-3 py-2 text-sm"
        onChange={event => onChange(event.target.value)}
        value={value}
      >
        <option value="">{placeholder}</option>
        {filtered.map(opt => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  )
}

export function FinanceFilterBar({
  freeText,
  onFreeTextChange,
  children,
}: {
  freeText: string
  onFreeTextChange: (value: string) => void
  children?: React.ReactNode
}) {
  return (
    <div className="grid gap-3 border-b border-[#eadfec] bg-[#fffafd] p-4 md:grid-cols-2 xl:grid-cols-4">
      <label className="block text-xs font-semibold text-[#76677d] md:col-span-2 xl:col-span-1">
        Busca livre
        <Input
          aria-label="Busca livre"
          className="mt-1"
          onChange={event => onFreeTextChange(event.target.value)}
          placeholder="Descrição, merchant, observação, conta…"
          value={freeText}
        />
      </label>
      {children}
    </div>
  )
}
