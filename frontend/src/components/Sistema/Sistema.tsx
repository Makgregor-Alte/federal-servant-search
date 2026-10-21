import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'

import { fetchServidores } from '../../api/servidores.js'
import type { SearchFilters, SearchPagination, Servidor } from '../../api/servidores.js'
import './Sistema.css'

const ufs = 'AC AL AP AM BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO'.split(' ')
const paginaInicial: SearchPagination = { page: 1, page_size: 20, total: 0, pages: 0 }

export function Sistema() {
  const [modoNome, setModoNome] = useState<'exact' | 'similar'>('exact')
  const [nome, setNome] = useState('')
  const [cargo, setCargo] = useState('')
  const [orgao, setOrgao] = useState('')
  const [uf, setUf] = useState('')
  const [porPagina, setPorPagina] = useState('20')
  const [resultados, setResultados] = useState<Servidor[]>([])
  const [paginacao, setPaginacao] = useState<SearchPagination>(paginaInicial)
  const [selecionado, setSelecionado] = useState<Servidor | null>(null)
  const [erro, setErro] = useState('')
  const [carregando, setCarregando] = useState(false)
  const [pesquisou, setPesquisou] = useState(false)
  const consulta = useRef<AbortController | null>(null)
  const filtrosAplicados = useRef<SearchFilters | null>(null)

  useEffect(() => () => consulta.current?.abort(), [])

  function limparResultados() {
    consulta.current?.abort()
    consulta.current = null
    filtrosAplicados.current = null
    setCarregando(false)
    setErro('')
    setPesquisou(false)
    setResultados([])
    setPaginacao(paginaInicial)
    setSelecionado(null)
  }

  function trocarModo(modo: 'exact' | 'similar') {
    setModoNome(modo)
    limparResultados()
  }

  async function executarBusca(filtros: SearchFilters, pagina: number) {
    consulta.current?.abort()
    const controller = new AbortController()
    consulta.current = controller
    setCarregando(true)
    setErro('')
    setSelecionado(null)
    try {
      const resposta = await fetchServidores(filtros, pagina, { signal: controller.signal })
      if (consulta.current !== controller) return
      setResultados(resposta.items)
      setPaginacao(resposta.pagination)
      setPesquisou(true)
    } catch (error) {
      if (consulta.current !== controller || controller.signal.aborted) return
      setResultados([])
      setPaginacao(paginaInicial)
      setPesquisou(false)
      setErro(error instanceof Error ? error.message : 'Não foi possível concluir a consulta.')
    } finally {
      if (consulta.current === controller) {
        consulta.current = null
        setCarregando(false)
      }
    }
  }

  function handleSubmit(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    const filtros: SearchFilters = {
      name: nome.trim(),
      name_mode: modoNome,
      position: cargo.trim(),
      agency: orgao.trim(),
      uf,
      page_size: porPagina,
    }
    if (!filtros.name && !filtros.position && !filtros.agency && !filtros.uf) {
      limparResultados()
      setErro('Informe pelo menos um filtro de consulta.')
      return
    }
    if (modoNome === 'similar' && filtros.name && !filtros.name.replaceAll('%', '').trim()) {
      limparResultados()
      setErro('O padrão de nome deve conter letras, não apenas %.')
      return
    }
    filtrosAplicados.current = filtros
    void executarBusca(filtros, 1)
  }

  function mudarPagina(pagina: number) {
    if (!filtrosAplicados.current || carregando || pagina < 1 || pagina > paginacao.pages) return
    void executarBusca(filtrosAplicados.current, pagina)
  }

  return (
    <div className="sistema">
      <main className="card">
        <h1>Consultar servidores</h1>
        <p className="subtitle">Pesquise por nome, cargo, órgão ou unidade federativa</p>

        <div className="abas" role="group" aria-label="Modo de pesquisa por nome">
          <button
            type="button"
            aria-pressed={modoNome === 'exact'}
            className={modoNome === 'exact' ? 'aba ativa' : 'aba'}
            onClick={() => trocarModo('exact')}
          >
            Nome exato
          </button>
          <button
            type="button"
            aria-pressed={modoNome === 'similar'}
            className={modoNome === 'similar' ? 'aba ativa' : 'aba'}
            onClick={() => trocarModo('similar')}
          >
            Nome semelhante
          </button>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <input
              id="nome-servidor"
              placeholder=" "
              autoComplete="off"
              maxLength={150}
              value={nome}
              onChange={evento => setNome(evento.target.value)}
            />
            <label htmlFor="nome-servidor">
              {modoNome === 'exact' ? 'Nome completo (opcional)' : 'Nome ou padrão com % (opcional)'}
            </label>
          </div>
          {modoNome === 'similar' && (
            <p className="dica">Use % como curinga: %MARIA%SILVA%, MARIA SILVA% ou MARIA%SILVA.</p>
          )}
          <div className="filtros-adicionais">
            <div className="field">
              <input
                id="cargo-servidor"
                placeholder=" "
                maxLength={150}
                value={cargo}
                onChange={evento => setCargo(evento.target.value)}
              />
              <label htmlFor="cargo-servidor">Cargo (opcional)</label>
            </div>
            <div className="field">
              <input
                id="orgao-servidor"
                placeholder=" "
                maxLength={150}
                value={orgao}
                onChange={evento => setOrgao(evento.target.value)}
              />
              <label htmlFor="orgao-servidor">Órgão (opcional)</label>
            </div>
          </div>
          <div className="filtros-adicionais">
            <div className="select-field">
              <label htmlFor="uf-servidor">Unidade federativa</label>
              <select id="uf-servidor" value={uf} onChange={evento => setUf(evento.target.value)}>
                <option value="">Todas as UFs</option>
                {ufs.map(sigla => <option key={sigla} value={sigla}>{sigla}</option>)}
              </select>
            </div>
            <div className="select-field">
              <label htmlFor="tamanho-pagina">Resultados por página</label>
              <select id="tamanho-pagina" value={porPagina} onChange={evento => setPorPagina(evento.target.value)}>
                {[10, 20, 50, 100].map(valor => <option key={valor} value={valor}>{valor}</option>)}
              </select>
            </div>
          </div>

          {erro && <p className="erro" role="alert">{erro}</p>}

          <button type="submit" className="btn-primary" disabled={carregando}>
            {carregando ? 'Consultando...' : 'Buscar'}
          </button>
        </form>

        <div aria-live="polite" aria-atomic="true" className="estado-busca">
          {carregando && <p>Buscando registros...</p>}
          {!carregando && pesquisou && resultados.length === 0 && <p>Nenhum registro encontrado para os filtros informados.</p>}
        </div>

        {selecionado && !carregando && (
          <section className="detalhe">
            <button type="button" className="voltar" onClick={() => setSelecionado(null)}>
              Voltar para a lista
            </button>
            <h2>{selecionado.nome}</h2>
            <dl>
              <div><dt>Cargo</dt><dd>{selecionado.cargo || 'Não informado'}</dd></div>
              <div><dt>Órgão</dt><dd>{selecionado.orgao || 'Não informado'}</dd></div>
              <div><dt>UF</dt><dd>{selecionado.uf || 'Não informada'}</dd></div>
              <div><dt>Fonte</dt><dd>{selecionado.fonte || 'Não informada'}</dd></div>
            </dl>
          </section>
        )}

        {!selecionado && !carregando && resultados.length > 0 && (
          <section className="lista" aria-label="Resultados da consulta">
            <p className="contagem">
              {paginacao.total.toLocaleString('pt-BR')} registro(s) encontrado(s)
            </p>
            <ul>
              {resultados.map(servidor => (
                <li key={servidor.id}>
                  <button type="button" className="item" onClick={() => setSelecionado(servidor)}>
                    <span>{servidor.nome}</span>
                    <span className="resumo-registro">
                      {[servidor.cargo, servidor.uf].filter(Boolean).join(' · ') || 'Detalhes do registro'}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {paginacao.pages > 1 && (
              <nav className="paginacao" aria-label="Páginas dos resultados">
                <button type="button" disabled={paginacao.page === 1} onClick={() => mudarPagina(paginacao.page - 1)}>
                  Anterior
                </button>
                <span>Página {paginacao.page} de {paginacao.pages}</span>
                <button type="button" disabled={paginacao.page >= paginacao.pages} onClick={() => mudarPagina(paginacao.page + 1)}>
                  Próxima
                </button>
              </nav>
            )}
          </section>
        )}
      </main>

    </div>
  )
}
