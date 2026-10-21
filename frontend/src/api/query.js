export function buildQuery(filters, page) {
  const params = new URLSearchParams({
    page: String(page),
    page_size: filters.page_size,
  })

  const name = filters.name.trim()
  if (name) {
    if (filters.name_mode === 'similar' && name.includes('%')) {
      params.set('similar', name)
    } else {
      params.set('name', name)
      params.set('name_mode', filters.name_mode)
    }
  }

  for (const field of ['position', 'agency', 'uf']) {
    const value = filters[field].trim()
    if (value) params.set(field, value)
  }

  return params.toString()
}
