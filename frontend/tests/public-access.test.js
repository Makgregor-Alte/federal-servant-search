import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const frontend = join(dirname(fileURLToPath(import.meta.url)), '..')
const source = path => readFileSync(join(frontend, 'src', path), 'utf8')

test('landing page and unknown paths direct visitors to the public search', () => {
  const app = source('App.tsx')
  assert.match(app, /path=['"]\/['"]\s+element=\{<Navigate to=['"]\/sistema['"] replace\s*\/>\}/)
  assert.match(app, /path=['"]\*['"]\s+element=\{<Navigate to=['"]\/sistema['"] replace\s*\/>\}/)
  assert.match(app, /path=['"]\/sistema['"]\s+element=\{<Sistema\s*\/>\}/)
})

test('login and registration links remain routable without claiming authentication', () => {
  const app = source('App.tsx')
  assert.match(app, /path=['"]\/login['"]/)
  assert.match(app, /path=['"]\/cadastro['"]/)
})

test('login does not collect passwords or simulate sessions', () => {
  const login = source('components/Login/Login.tsx')
  assert.doesNotMatch(login, /<form\b|<input\b|type=['"]password['"]|console\.|fetch\(|localStorage|sessionStorage/)
  assert.match(login, /não possui autenticação/i)
  assert.match(login, /<Link to="\/sistema"/)
})

test('registration does not collect personal information or claim to create an account', () => {
  const cadastro = source('components/Cadastro/Cadastro.tsx')
  assert.doesNotMatch(cadastro, /<form\b|<input\b|type=['"]password['"]|console\.|fetch\(/)
  assert.match(cadastro, /Não é necessário criar uma conta/)
  assert.match(cadastro, /<Link to="\/sistema"/)
})

test('header has meaningful text and links to the working feature', () => {
  const header = source('components/Header/Header.tsx')
  assert.match(header, /to="\/sistema"/)
  assert.doesNotMatch(header, /\*LOGO\*|COMPANY/)
})

test('search page has no fictitious logout and continues to call the real API', () => {
  const screen = source('components/Sistema/Sistema.tsx')
  assert.doesNotMatch(screen, /Quer trocar de conta\?|>Sair<|to="\/login"/)
  assert.match(screen, /fetchServidores\(/)
  assert.match(screen, /role="alert"/)
  assert.match(screen, /aria-live="polite"/)
})

test('no frontend TSX module prints credentials or form contents to the console', () => {
  function checkDirectory(directory) {
    for (const item of readdirSync(directory, { withFileTypes: true })) {
      const full = join(directory, item.name)
      if (item.isDirectory()) checkDirectory(full)
      else if (item.name.endsWith('.tsx')) {
        assert.doesNotMatch(readFileSync(full, 'utf8'), /console\.(?:log|debug|info|warn|error)\s*\(/, full)
      }
    }
  }
  checkDirectory(join(frontend, 'src'))
})
