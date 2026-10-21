import { buildQuery } from './query.js'

export class SearchApiError extends Error {
  constructor(message, status = null) {
    super(message)
    this.name = 'SearchApiError'
    this.status = status
  }
}

function responseError(status) {
  if (status === 400) return 'Os filtros não foram aceitos. Revise os campos e tente novamente.'
  if (status === 404) return 'A página solicitada não está mais disponível. Faça uma nova busca.'
  if (status === 429) return 'Muitas consultas em sequência. Aguarde alguns segundos e tente novamente.'
  if (status === 503 || status === 502 || status === 504) {
    return 'A consulta está temporariamente indisponível. Tente novamente mais tarde.'
  }
  return 'Não foi possível concluir a consulta. Tente novamente.'
}

function isNonNegativeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0
}

export function validateSearchResponse(data, requestedPage, requestedSize) {
  if (!data || typeof data !== 'object' || !Array.isArray(data.items)) return false
  const p = data.pagination
  if (!p || typeof p !== 'object') return false
  if (p.page !== requestedPage || p.page_size !== requestedSize) return false
  if (!isNonNegativeInteger(p.total) || !isNonNegativeInteger(p.pages)) return false
  if (p.pages !== Math.ceil(p.total / p.page_size)) return false
  if (data.items.length > p.page_size || data.items.length > p.total) return false
  return data.items.every(item =>
    item && typeof item === 'object' &&
    Number.isSafeInteger(item.id) &&
    typeof item.nome === 'string' &&
    ['cargo', 'orgao', 'uf', 'fonte'].every(field =>
      Object.hasOwn(item, field) && (item[field] === null || typeof item[field] === 'string')
    )
  )
}

export async function fetchServidores(filters, page, options = {}) {
  const query = buildQuery(filters, page)
  let response
  try {
    response = await (options.fetcher ?? fetch)(`/api/servidores?${query}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: options.signal,
    })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new SearchApiError('Não foi possível conectar à API. Verifique a conexão e tente novamente.')
  }
  if (!response.ok) throw new SearchApiError(responseError(response.status), response.status)
  let body
  try {
    body = await response.json()
  } catch {
    throw new SearchApiError('A API retornou uma resposta inválida.')
  }
  if (!validateSearchResponse(body, page, Number(filters.page_size))) {
    throw new SearchApiError('A API retornou dados em um formato inesperado.')
  }
  return body
}
