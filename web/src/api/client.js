export async function request(path, options = {}) {
  const response = await fetch(path, options)
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body?.detail
    throw new Error(typeof detail === 'string' ? detail : `요청 실패 (${response.status})`)
  }
  return body
}
