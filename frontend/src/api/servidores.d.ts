export interface SearchFilters {
  name: string
  name_mode: 'exact' | 'similar'
  position: string
  agency: string
  uf: string
  page_size: string
}

export interface Servidor {
  id: number
  nome: string
  cargo: string | null
  orgao: string | null
  uf: string | null
  fonte: string | null
}

export interface SearchPagination {
  page: number
  page_size: number
  total: number
  pages: number
}

export interface SearchResponse {
  items: Servidor[]
  pagination: SearchPagination
}

export interface FetchOptions {
  signal?: AbortSignal
  fetcher?: typeof fetch
}

export class SearchApiError extends Error {
  status: number | null
  constructor(message: string, status?: number | null)
}

export function validateSearchResponse(data: unknown, requestedPage: number, requestedSize: number): boolean
export function fetchServidores(filters: SearchFilters, page: number, options?: FetchOptions): Promise<SearchResponse>
