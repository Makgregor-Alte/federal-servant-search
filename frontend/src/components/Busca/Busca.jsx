import { useEffect, useState } from 'react'
import './Busca.css'

const initialFilters = {
  name: '',
  name_mode: 'similar',
  position: '',
  agency: '',
  uf: '',
  page_size: '20',
}

const estados = 'AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.split(' ')

function humanNumber(value) {
  return new Intl.NumberFormat('pt-BR').format(value ?? 0)
}

function buildQuery(filters, page) {
  const params = new URLSearchParams({ page: String(page), page_size: filters.page_size })
  for (const field of ['name', 'position', 'agency', 'uf']) {
    const value = filters[field].trim()
    if (value) params.set(field, value)
  }
  if (filters.name.trim()) params.set('name_mode', filters.name_mode)
  return params.toString()
}

export function Busca() {
  const [form, setForm] = useState(initialFilters)
  const [query, setQuery] = useState(initialFilters)
  const [page, setPage] = useState(1)
  const [response, setResponse] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      try {
        const result = await fetch(`/api/servidores?${buildQuery(query, page)}`, {
          signal: controller.signal,
          headers: { Accept: 'application/json' },
        })
        const data = await result.json().catch(() => null)
        if (!result.ok) {
          throw new Error(data?.message || 'O servidor não conseguiu concluir a pesquisa.')
        }
        if (!Array.isArray(data?.items) || !data?.pagination) {
          throw new Error('A API retornou uma resposta inesperada.')
        }
        if (!controller.signal.aborted) setResponse(data)
      } catch (err) {
        if (!controller.signal.aborted) {
          setResponse(null)
          setError(err instanceof Error ? err.message : 'Falha na comunicação com a API.')
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    load()
    return () => controller.abort()
  }, [query, page])

  function update(event) {
    const { name, value } = event.target
    setForm((old) => ({ ...old, [name]: value }))
  }

  function submit(event) {
    event.preventDefault()
    setLoading(true)
    setError('')
    setPage(1)
    setQuery({ ...form })
  }

  function reset() {
    setLoading(true)
    setError('')
    setForm({ ...initialFilters })
    setQuery({ ...initialFilters })
    setPage(1)
  }

  function changePage(next) {
    setLoading(true)
    setError('')
    setPage(next)
  }

  const pagination = response?.pagination
  const items = response?.items || []
  const anyFilter = ['name', 'position', 'agency', 'uf'].some((key) => query[key].trim())
  const pages = pagination?.pages ?? 0

  return (
    <div className="busca-layout">
      <header className="busca-header">
        <div className="busca-brand">
          <span className="busca-brand-mark" aria-hidden="true">F</span>
          <div>
            <strong>Federal Servant Search</strong>
            <span>Projeto acadêmico · Sistemas para Internet II</span>
          </div>
        </div>
        <span className="busca-header-status">Consulta pública · acesso livre</span>
      </header>

      <main className="busca-main">
        <section className="busca-intro">
          <p className="busca-overline">PESQUISA NO EXECUTIVO FEDERAL</p>
          <h1>Consulta de servidores federais</h1>
          <p>Pesquise registros por nome, cargo, órgão e unidade federativa. Os resultados dependem das bases de dados efetivamente importadas.</p>
        </section>

        <section className="busca-card" aria-labelledby="titulo-filtros">
          <div className="busca-section-heading">
            <h2 id="titulo-filtros">Filtros de pesquisa</h2>
            <span>Combine campos para refinar a busca</span>
          </div>
          <form onSubmit={submit} className="busca-form">
            <div className="busca-field busca-field-name">
              <label htmlFor="f-nome">Nome do servidor</label>
              <input id="f-nome" name="name" placeholder="Digite um nome" value={form.name} onChange={update} maxLength={150} />
            </div>
            <div className="busca-field busca-field-mode">
              <label htmlFor="f-modo">Tipo de correspondência</label>
              <select id="f-modo" name="name_mode" value={form.name_mode} onChange={update}>
                <option value="similar">Nome semelhante</option>
                <option value="exact">Nome exato</option>
              </select>
            </div>
            <div className="busca-field">
              <label htmlFor="f-cargo">Cargo ou profissão</label>
              <input id="f-cargo" name="position" placeholder="Ex.: Analista" value={form.position} onChange={update} maxLength={150} />
            </div>
            <div className="busca-field">
              <label htmlFor="f-orgao">Órgão ou instituição</label>
              <input id="f-orgao" name="agency" placeholder="Ex.: Universidade" value={form.agency} onChange={update} maxLength={150} />
            </div>
            <div className="busca-field">
              <label htmlFor="f-uf">Estado (UF)</label>
              <select id="f-uf" name="uf" value={form.uf} onChange={update}>
                <option value="">Todos os estados</option>
                {estados.map((uf) => <option value={uf} key={uf}>{uf}</option>)}
              </select>
            </div>
            <div className="busca-field">
              <label htmlFor="f-page-size">Itens por página</label>
              <select id="f-page-size" name="page_size" value={form.page_size} onChange={update}>
                <option value="10">10 resultados</option>
                <option value="20">20 resultados</option>
                <option value="50">50 resultados</option>
              </select>
            </div>
            <div className="busca-actions">
              <button type="submit" className="busca-primary" disabled={loading}>
                {loading ? 'Carregando...' : 'Pesquisar servidores'}
              </button>
              <button type="button" className="busca-reset" onClick={reset}>Limpar filtros</button>
            </div>
          </form>
        </section>

        <section className="busca-card busca-results" aria-labelledby="titulo-resultados" aria-busy={loading}>
          <div className="busca-section-heading busca-results-header">
            <div>
              <h2 id="titulo-resultados">Resultados da pesquisa</h2>
              <p aria-live="polite">{loading ? 'Consultando banco de dados...' : error ? 'Falha na consulta' : `${humanNumber(pagination?.total)} registro(s) encontrado(s)`}</p>
            </div>
            {pagination && !loading && <span className="busca-page-label">Página {pagination.page} de {Math.max(pages, 1)}</span>}
          </div>

          {error && <div role="alert" className="busca-alert">{error} Verifique se o Docker e a API estão em execução.</div>}
          {!error && loading && <div className="busca-placeholder" role="status">Buscando registros...</div>}
          {!error && !loading && items.length === 0 && (
            <div className="busca-empty">
              <span className="busca-empty-symbol" aria-hidden="true">∅</span>
              <h3>Nenhum registro encontrado</h3>
              <p>{anyFilter ? 'Tente reduzir os filtros. Se nenhum arquivo oficial foi importado, a base pode estar vazia.' : 'Ainda não há resultados disponíveis. A importação dos datasets oficiais pode estar pendente.'}</p>
            </div>
          )}
          {!error && !loading && items.length > 0 && (
            <div className="busca-table-scroll">
              <table className="busca-table">
                <thead><tr><th>Nome</th><th>Cargo / profissão</th><th>Órgão</th><th>UF</th><th>Fonte</th></tr></thead>
                <tbody>{items.map((person) => (
                  <tr key={person.id}>
                    <td className="busca-person-name">{person.nome || '—'}</td>
                    <td>{person.cargo || '—'}</td>
                    <td>{person.orgao || '—'}</td>
                    <td>{person.uf || '—'}</td>
                    <td>{person.fonte || '—'}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
          {!loading && !error && pages > 1 && (
            <div className="busca-pagination">
              <button type="button" onClick={() => changePage(Math.max(1, page - 1))} disabled={page <= 1}>Anterior</button>
              <span>{page} / {pages}</span>
              <button type="button" onClick={() => changePage(Math.min(pages, page + 1))} disabled={page >= pages}>Próxima</button>
            </div>
          )}
        </section>
        <footer className="busca-footer">Federal Servant Search · Projeto acadêmico. As informações são limitadas aos datasets importados.</footer>
      </main>
    </div>
  )
}
