import test from 'node:test'
import assert from 'node:assert/strict'
import { fetchServidores, SearchApiError, validateSearchResponse } from '../src/api/servidores.js'

const filters = {
  name: 'Maria', name_mode: 'exact', position: '', agency: '', uf: '', page_size: '20',
}
const sample = {
  items: [{ id: 4, nome: 'Maria Oliveira', cargo: 'Analista', orgao: 'Universidade', uf: 'RS', fonte: 'carreiras' }],
  pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
}

function fakeResponse(body = sample, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() { return body },
  }
}

test('real request contract uses relative API URL and accepts structured data', async () => {
  let request
  const result = await fetchServidores({ ...filters, name_mode: 'similar', name: '%João%Silva%', position: 'Técnico', agency: 'Educação', uf: 'RS' }, 1, {
    fetcher: async (url, options) => {
      request = { url, options }
      return fakeResponse()
    },
  })
  assert.deepEqual(result, sample)
  const url = new URL(request.url, 'http://localhost')
  assert.equal(url.pathname, '/api/servidores')
  assert.equal(url.searchParams.get('similar'), '%João%Silva%')
  assert.equal(url.searchParams.get('position'), 'Técnico')
  assert.equal(url.searchParams.get('agency'), 'Educação')
  assert.equal(url.searchParams.get('uf'), 'RS')
  assert.equal(url.searchParams.get('page'), '1')
  assert.equal(request.options.method, 'GET')
})

test('page two uses API pagination rather than slicing the first page', async () => {
  let requested
  const second = { items: [], pagination: { page: 2, page_size: 20, total: 21, pages: 2 } }
  await fetchServidores(filters, 2, {
    fetcher: async url => {
      requested = new URL(url, 'http://localhost').searchParams
      return fakeResponse(second)
    },
  })
  assert.equal(requested.get('page'), '2')
  assert.equal(requested.get('page_size'), '20')
})

test('zero-result response is accepted', async () => {
  const empty = { items: [], pagination: { page: 1, page_size: 20, total: 0, pages: 0 } }
  assert.deepEqual(await fetchServidores(filters, 1, { fetcher: async () => fakeResponse(empty) }), empty)
})

test('nullable official source fields are accepted but imaginary personal fields are not required', () => {
  const record = { id: 1, nome: 'Ana', cargo: null, orgao: null, uf: null, fonte: 'aposentados' }
  assert.equal(validateSearchResponse({ items: [record], pagination: { page: 1, page_size: 20, total: 1, pages: 1 } }, 1, 20), true)
})

test('invalid pagination and record shapes are rejected', () => {
  const bad = [
    { ...sample, pagination: { ...sample.pagination, pages: 99 } },
    { ...sample, pagination: { ...sample.pagination, page: 2 } },
    { ...sample, items: [{ ...sample.items[0], id: '4' }] },
    { ...sample, items: [{ id: 4, nome: 'Maria' }] },
    { ...sample, items: [{ ...sample.items[0], cargo: [] }] },
    { ...sample, items: {} },
    { ...sample, pagination: { ...sample.pagination, total: -1 } },
  ]
  for (const data of bad) {
    assert.equal(validateSearchResponse(data, 1, 20), false)
  }
})

test('invalid JSON is communicated without exposing response internals', async () => {
  await assert.rejects(
    () => fetchServidores(filters, 1, { fetcher: async () => ({ ok: true, json: async () => { throw new SyntaxError('secret') } }) }),
    error => error instanceof SearchApiError && /resposta inválida/.test(error.message) && !error.message.includes('secret'),
  )
})

test('invalid structure is reported as a clear API failure', async () => {
  await assert.rejects(
    () => fetchServidores(filters, 1, { fetcher: async () => fakeResponse({ items: 'foo', pagination: null }) }),
    error => error instanceof SearchApiError && /formato inesperado/.test(error.message),
  )
})

test('status 400, 404, 429, 503 and 500 have appropriate descriptions', async () => {
  for (const [status, expected] of [
    [400, 'filtros'], [404, 'página'], [429, 'Aguarde'], [503, 'indisponível'], [500, 'Não foi possível'],
  ]) {
    await assert.rejects(
      () => fetchServidores(filters, 1, { fetcher: async () => fakeResponse({ error: 'internal_data' }, status) }),
      error => error.status === status && error.message.includes(expected) && !error.message.includes('internal_data'),
    )
  }
})

test('network errors are communicated without exposing system details', async () => {
  await assert.rejects(
    () => fetchServidores(filters, 1, { fetcher: async () => { throw new TypeError('private.internal.host') } }),
    error => error instanceof SearchApiError && /conectar/.test(error.message) && !error.message.includes('private'),
  )
})

test('aborted requests propagate AbortError for race handling', async () => {
  const abort = new Error('Aborted')
  abort.name = 'AbortError'
  await assert.rejects(
    () => fetchServidores(filters, 1, { fetcher: async () => { throw abort } }),
    error => error === abort,
  )
})

test('AbortSignal is passed to fetch', async () => {
  const controller = new AbortController()
  let signal
  await fetchServidores(filters, 1, { signal: controller.signal, fetcher: async (_url, options) => {
    signal = options.signal
    return fakeResponse()
  } })
  assert.equal(signal, controller.signal)
})
