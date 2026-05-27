const csvCache = new Map()

function splitCsvLine(line, separator = ';') {
  const out = []
  let current = ''
  let inQuotes = false

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i]
    const next = line[i + 1]

    if (char === '"' && inQuotes && next === '"') {
      current += '"'
      i += 1
      continue
    }

    if (char === '"') {
      inQuotes = !inQuotes
      continue
    }

    if (char === separator && !inQuotes) {
      out.push(current.trim())
      current = ''
      continue
    }

    current += char
  }

  out.push(current.trim())
  return out
}

function parseCsv(content, separator = ';') {
  const rows = content.replace(/^\uFEFF/, '').split(/\r?\n/).filter(Boolean)
  if (rows.length === 0) return []

  const headers = splitCsvLine(rows[0], separator)
  return rows.slice(1).map((line) => {
    const values = splitCsvLine(line, separator)
    const record = {}
    headers.forEach((header, index) => {
      record[header] = values[index] ?? ''
    })
    return record
  })
}

export async function loadCsv(url, { skipCache = false } = {}) {
  if (skipCache) {
    csvCache.delete(url)
  } else if (csvCache.has(url)) {
    return csvCache.get(url)
  }

  const response = await fetch(url, skipCache ? { cache: 'no-store' } : {})
  if (!response.ok) {
    throw new Error(`Failed to load ${url}: ${response.status}`)
  }

  const content = await response.text()
  const parsed = parseCsv(content, ';')
  csvCache.set(url, parsed)
  return parsed
}
