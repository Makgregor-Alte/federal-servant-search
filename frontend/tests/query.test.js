import test from 'node:test'
import assert from 'node:assert/strict'
import { buildQuery } from '../src/api/query.js'

const filters = {
  name: '',
  name_mode: 'similar',
  position: '',
  agency: '',
  uf: '',
  page_size: '20',
}

function params(overrides = {}, page = 1) {
  return new URLSearchParams(buildQuery({ ...filters, ...overrides }, page))
}

test('sends only pagination for an empty search', () => {
  const q = params()
  assert.deepEqual([...q.keys()], ['page', 'page_size'])
  assert.equal(q.get('page'), '1')
  assert.equal(q.get('page_size'), '20')
})

test('exact name uses name and name_mode', () => {
  const q = params({ name: '  Maria da Silva ', name_mode: 'exact' })
  assert.equal(q.get('name'), 'Maria da Silva')
  assert.equal(q.get('name_mode'), 'exact')
  assert.equal(q.has('similar'), false)
})

test('fuzzy name without percent uses name and name_mode', () => {
  const q = params({ name: 'Mariana', name_mode: 'similar' })
  assert.equal(q.get('name'), 'Mariana')
  assert.equal(q.get('name_mode'), 'similar')
  assert.equal(q.has('similar'), false)
})

test('similarity patterns use the dedicated API parameter', () => {
  for (const name of ['%NOME%SOBRENOME%', 'NOME SOBRENOME%', 'NOME%SOBRENOME']) {
    const q = params({ name, name_mode: 'similar' })
    assert.equal(q.get('similar'), name)
    assert.equal(q.has('name'), false)
    assert.equal(q.has('name_mode'), false)
  }
})

test('literal percent is preserved in exact searches', () => {
  const q = params({ name: '100%', name_mode: 'exact' })
  assert.equal(q.get('name'), '100%')
  assert.equal(q.has('similar'), false)
})

test('combined filters and pagination preserve values and accents', () => {
  const q = params({ name: '%João%Silva%', position: '  Técnico ', agency: ' Educação ', uf: 'RS', page_size: '50' }, 3)
  assert.equal(q.get('similar'), '%João%Silva%')
  assert.equal(q.get('position'), 'Técnico')
  assert.equal(q.get('agency'), 'Educação')
  assert.equal(q.get('uf'), 'RS')
  assert.equal(q.get('page'), '3')
  assert.equal(q.get('page_size'), '50')
})

test('URLSearchParams encodes reserved characters without losing information', () => {
  const q = params({ name: 'Ana & Maria? #1', name_mode: 'similar' })
  assert.equal(q.get('name'), 'Ana & Maria? #1')
})
