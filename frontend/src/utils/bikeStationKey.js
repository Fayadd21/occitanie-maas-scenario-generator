function formatBikeStationNameFromLocalized(value) {
  if (value == null) return ''
  if (typeof value === 'string') return value.trim()
  if (Array.isArray(value)) {
    const preferred = ['fr', 'en']
    const byLang = {}
    for (const item of value) {
      if (!item || typeof item !== 'object' || item.text == null) continue
      byLang[String(item.language || '').toLowerCase()] = String(item.text).trim()
    }
    for (const lang of preferred) {
      if (byLang[lang]) return byLang[lang]
    }
    const first = value.find((item) => item && item.text != null)
    return first ? String(first.text).trim() : ''
  }
  if (typeof value === 'object' && value.text != null) {
    return String(value.text).trim()
  }
  return ''
}

export function formatBikeStationName(value) {
  if (value == null || value === '') return ''
  if (typeof value !== 'string') return formatBikeStationNameFromLocalized(value)
  const trimmed = value.trim()
  if (!trimmed.startsWith('[') && !trimmed.startsWith('{')) return trimmed
  try {
    const normalized = trimmed
      .replace(/'/g, '"')
      .replace(/\bNone\b/g, 'null')
      .replace(/\bTrue\b/g, 'true')
      .replace(/\bFalse\b/g, 'false')
    return formatBikeStationNameFromLocalized(JSON.parse(normalized)) || trimmed
  } catch {
    const match = trimmed.match(/['"]text['"]\s*:\s*['"]([^'"]+)['"]/)
    return match ? match[1] : trimmed
  }
}

export function bikeStationKeyFromRow(row) {
  if (!row || typeof row !== 'object') return null
  const composite = row.city_station_id != null && String(row.city_station_id).trim()
  if (composite) return composite
  const city = row.city_id != null && String(row.city_id).trim()
  const sid = row.station_id != null && String(row.station_id).trim()
  if (city && sid) return `${city}:${sid}`
  return null
}

export function stationCapacityFromRow(row) {
  if (!row || typeof row !== 'object') return null
  const raw = row.capacity
  if (raw === undefined || raw === null || raw === '') return null
  const n = Number(raw)
  if (!Number.isFinite(n) || n < 0) return null
  return Math.round(n)
}

export function clampAvailableBikes(value, capacity) {
  const bikes = Math.max(0, Math.round(Number(value)))
  if (!Number.isFinite(bikes)) return 0
  if (capacity == null) return bikes
  return Math.min(bikes, capacity)
}

export function baseAvailableBikesFromRow(row) {
  if (!row || typeof row !== 'object') return 0
  for (const field of ['available_bikes', 'num_bikes_available']) {
    if (row[field] === undefined || row[field] === '') continue
    const n = Number(row[field])
    if (Number.isFinite(n)) {
      return clampAvailableBikes(n, stationCapacityFromRow(row))
    }
  }
  return 0
}

export function effectiveAvailableBikes(row, overrides) {
  const capacity = stationCapacityFromRow(row)
  const key = bikeStationKeyFromRow(row)
  if (key && overrides && Object.prototype.hasOwnProperty.call(overrides, key)) {
    const v = Number(overrides[key])
    if (Number.isFinite(v)) return clampAvailableBikes(v, capacity)
  }
  return baseAvailableBikesFromRow(row)
}


export function mergeBikeRowForDisplay(row, overrides) {
  const merged = { ...row }
  if (merged.name != null && merged.name !== '') {
    merged.name = formatBikeStationName(merged.name)
  }
  const key = bikeStationKeyFromRow(row)
  if (key && overrides && Object.prototype.hasOwnProperty.call(overrides, key)) {
    const v = Number(overrides[key])
    if (Number.isFinite(v)) {
      merged.available_bikes = String(
        clampAvailableBikes(v, stationCapacityFromRow(row)),
      )
    }
  }
  return merged
}
