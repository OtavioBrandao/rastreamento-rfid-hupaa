import { useState, type FormEvent } from 'react'
import { Icon } from './layout/Icon'

export function SearchBar({ onSearch }: { onSearch: (query: string) => void }) {
  const [value, setValue] = useState('')
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSearch(value)
  }
  return <form className="search-form" role="search" onSubmit={submit}>
    <label htmlFor="equipment-search">Qual equipamento você procura?</label>
    <div className="search-control">
      <span className="search-icon" aria-hidden="true"><Icon name="search" size={20}/></span>
      <input id="equipment-search" type="search" value={value} onChange={(event) => setValue(event.target.value)} placeholder="Buscar equipamento, patrimônio ou EPC" />
      <button type="submit">Buscar</button>
    </div>
  </form>
}
