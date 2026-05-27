function toFeatureCollection(input) {
  if (!input || typeof input !== 'object') return null
  if (input.type === 'FeatureCollection' && Array.isArray(input.features)) {
    return input
  }
  if (input.type === 'Feature' && input.geometry) {
    return { type: 'FeatureCollection', features: [input] }
  }
  if (input.type === 'Polygon' || input.type === 'MultiPolygon') {
    return {
      type: 'FeatureCollection',
      features: [{ type: 'Feature', properties: {}, geometry: input }],
    }
  }
  if (input.type === 'GeometryCollection' && Array.isArray(input.geometries)) {
    const features = []
    for (const g of input.geometries) {
      if (g && (g.type === 'Polygon' || g.type === 'MultiPolygon')) {
        features.push({ type: 'Feature', properties: {}, geometry: g })
      }
    }
    return { type: 'FeatureCollection', features }
  }
  return null
}

function polygonFeaturesOnly(fc) {
  const features = []
  for (const f of fc.features || []) {
    if (!f || typeof f !== 'object') continue
    const g = f.geometry
    if (!g || typeof g !== 'object') continue
    if (g.type !== 'Polygon' && g.type !== 'MultiPolygon') continue
    features.push({
      type: 'Feature',
      properties: { ...(f.properties || {}), shape: f.properties?.shape || 'imported' },
      geometry: g,
    })
  }
  return { type: 'FeatureCollection', features }
}

export function parseAreaGeoJson(input) {
  const fc = toFeatureCollection(input)
  if (!fc) {
    return { ok: false, reason: 'Expected a GeoJSON FeatureCollection, Feature, Polygon, MultiPolygon, or GeometryCollection.' }
  }
  const filtered = polygonFeaturesOnly(fc)
  if (!filtered.features.length) {
    return {
      ok: false,
      reason: 'No usable Polygon or MultiPolygon geometry found. Points and lines are not supported as generation areas.',
    }
  }
  return { ok: true, featureCollection: filtered }
}
