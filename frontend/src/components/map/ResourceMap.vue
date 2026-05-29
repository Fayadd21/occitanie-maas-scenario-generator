<script setup>
import { onMounted, onBeforeUnmount, watch, ref, nextTick } from 'vue'
import L from 'leaflet'
import '@geoman-io/leaflet-geoman-free'
import { loadCsv } from '../../services/csvService'
import { parseAreaGeoJson } from '../../utils/areaGeoJson'
import { mergeBikeRowForDisplay, formatBikeStationName } from '../../utils/bikeStationKey'

const props = defineProps({
  mapView: {
    type: Object,
    required: true,
  },
  layers: {
    type: Array,
    required: true,
  },
  visibility: {
    type: Object,
    required: true,
  },
  clearSelectionSignal: {
    type: Number,
    default: 0,
  },
  bikeAvailabilityOverrides: {
    type: Object,
    default: () => ({}),
  },
})

const emit = defineEmits(['selection-change', 'bike-station-click'])

const mapRootEl = ref(null)
let map = null
let mapResizeObserver = null
const layerGroups = new Map()
const layerLoadVersion = new Map()
let drawnItems = null

function buildPopup(record, fields) {
  return fields
    .filter((field) => record[field] !== undefined && record[field] !== '')
    .map((field) => {
      const value = field === 'name' ? formatBikeStationName(record[field]) : record[field]
      return `<strong>${field}</strong>: ${value}`
    })
    .join('<br/>')
}

async function ensureLayerOnMap(layerConfig) {
  if (!map) return
  const currentVersion = (layerLoadVersion.get(layerConfig.id) || 0) + 1
  layerLoadVersion.set(layerConfig.id, currentVersion)

  if (layerGroups.has(layerConfig.id)) {
    const group = layerGroups.get(layerConfig.id)
    if (!map.hasLayer(group)) {
      group.addTo(map)
    }
    return
  }

  if (!layerConfig.url) return
  const group = L.layerGroup()

  if (layerConfig.format === 'geojson') {
    const response = await fetch(layerConfig.url)
    if (!response.ok) {
      throw new Error(`Failed to load ${layerConfig.url}: ${response.status}`)
    }
    const featureCollection = await response.json()
    const geoJsonLayer = L.geoJSON(featureCollection, {
      pointToLayer: (_feature, latlng) =>
        L.circleMarker(latlng, {
          radius: 3,
          weight: 1,
          color: layerConfig.color,
          fillColor: layerConfig.color,
          fillOpacity: 0.6,
        }),
      onEachFeature: (feature, layer) => {
        const properties = feature.properties || {}
        const popup = buildPopup(properties, layerConfig.popupFields || [])
        if (popup) {
          layer.bindPopup(popup)
        }
      },
    })
    geoJsonLayer.addTo(group)
  } else {
    const points = await loadCsv(layerConfig.url, { skipCache: Boolean(layerConfig.skipCsvCache) })
    points.forEach((row) => {
      const lat = Number(row[layerConfig.latField])
      const lon = Number(row[layerConfig.lonField])
      if (Number.isNaN(lat) || Number.isNaN(lon)) return

      const marker = L.circleMarker([lat, lon], {
        radius: 4,
        weight: 1,
        color: layerConfig.color,
        fillColor: layerConfig.color,
        fillOpacity: 0.7,
      })

      if (layerConfig.id === 'bikesharing') {
        marker._bikeBaseRow = row
        const refreshBikePopup = () => {
          const merged = mergeBikeRowForDisplay(marker._bikeBaseRow, props.bikeAvailabilityOverrides)
          const html = buildPopup(merged, layerConfig.popupFields)
          if (html) marker.setPopupContent(html)
        }
        marker.on('popupopen', refreshBikePopup)
        marker.on('click', () => {
          emit('bike-station-click', { row: { ...marker._bikeBaseRow } })
        })
        const merged = mergeBikeRowForDisplay(row, props.bikeAvailabilityOverrides)
        const popup = buildPopup(merged, layerConfig.popupFields)
        if (popup) {
          marker.bindPopup(popup)
        }
      } else {
        const popup = buildPopup(row, layerConfig.popupFields)
        if (popup) {
          marker.bindPopup(popup)
        }
      }

      marker.addTo(group)
    })
  }

  if (!props.visibility[layerConfig.id]) {
    return
  }
  if (layerLoadVersion.get(layerConfig.id) !== currentVersion) {
    return
  }

  if (layerGroups.has(layerConfig.id)) {
    const oldGroup = layerGroups.get(layerConfig.id)
    if (map.hasLayer(oldGroup)) {
      map.removeLayer(oldGroup)
    }
  }
  layerGroups.set(layerConfig.id, group)
  if (props.visibility[layerConfig.id]) {
    group.addTo(map)
  }
}

function removeLayerFromMap(layerId) {
  layerLoadVersion.set(layerId, (layerLoadVersion.get(layerId) || 0) + 1)
  if (!map || !layerGroups.has(layerId)) return
  map.removeLayer(layerGroups.get(layerId))
}

function circleToPolygon(circle, points = 64) {
  const center = circle.getLatLng()
  const radiusMeters = circle.getRadius()
  const earthRadius = 6378137
  const lat1 = (center.lat * Math.PI) / 180
  const lon1 = (center.lng * Math.PI) / 180
  const angularDistance = radiusMeters / earthRadius

  const ring = []
  for (let i = 0; i <= points; i += 1) {
    const bearing = (2 * Math.PI * i) / points
    const lat2 = Math.asin(
      Math.sin(lat1) * Math.cos(angularDistance) +
        Math.cos(lat1) * Math.sin(angularDistance) * Math.cos(bearing),
    )
    const lon2 =
      lon1 +
      Math.atan2(
        Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(lat1),
        Math.cos(angularDistance) - Math.sin(lat1) * Math.sin(lat2),
      )

    ring.push([(lon2 * 180) / Math.PI, (lat2 * 180) / Math.PI])
  }

  return {
    type: 'Feature',
    properties: {
      shape: 'circle',
      radius_m: Math.round(radiusMeters),
    },
    geometry: {
      type: 'Polygon',
      coordinates: [ring],
    },
  }
}

function normalizeDrawnLayer(layer) {
  if (layer instanceof L.Circle) {
    return circleToPolygon(layer)
  }

  const geojson = layer.toGeoJSON()
  if (!geojson.properties) {
    geojson.properties = {}
  }
  if (layer instanceof L.Rectangle) {
    geojson.properties.shape = 'rectangle'
  } else if (layer instanceof L.Polygon) {
    geojson.properties.shape = 'polygon'
  }
  return geojson
}

function emitCurrentSelection() {
  const fc = getSelectionFeatureCollection()
  emit('selection-change', fc)
}

function getSelectionFeatureCollection() {
  if (!drawnItems || drawnItems.getLayers().length === 0) {
    return null
  }
  const layers = drawnItems.getLayers().map((layer) => normalizeDrawnLayer(layer))
  return {
    type: 'FeatureCollection',
    features: layers,
  }
}

const IMPORTED_STYLE = {
  color: '#2563eb',
  weight: 2,
  fillColor: '#3b82f6',
  fillOpacity: 0.2,
}

function applyImportedGeoJson(parsed) {
  const parsedResult = parseAreaGeoJson(parsed)
  if (!parsedResult.ok) {
    return { ok: false, reason: parsedResult.reason }
  }
  if (!map || !drawnItems) {
    return { ok: false, reason: 'Map is not ready yet.' }
  }

  drawnItems.clearLayers()
  L.geoJSON(parsedResult.featureCollection, {
    style: () => IMPORTED_STYLE,
    onEachFeature: (_feature, layer) => {
      drawnItems.addLayer(layer)
    },
  })

  try {
    const b = drawnItems.getBounds()
    map.fitBounds(b, { padding: [28, 28], maxZoom: 13, animate: false })
  } catch {
    /* ignore invalid bounds */
  }

  emitCurrentSelection()
  requestAnimationFrame(() => invalidateMapSize())
  return { ok: true }
}

let resizeFrame = null

function invalidateMapSize() {
  if (!map) return
  if (resizeFrame !== null) {
    cancelAnimationFrame(resizeFrame)
  }
  resizeFrame = requestAnimationFrame(() => {
    resizeFrame = null
    if (map) {
      map.invalidateSize({ animate: false })
    }
  })
}

defineExpose({
  applyImportedGeoJson,
  getSelectionGeoJson: getSelectionFeatureCollection,
  invalidateMapSize,
})

function clearSelectionLayers() {
  if (!drawnItems) return
  drawnItems.clearLayers()
  emitCurrentSelection()
}

function setupDrawing() {
  drawnItems = new L.FeatureGroup()
  map.addLayer(drawnItems)

  map.pm.addControls({
    position: 'topleft',
    drawCircleMarker: false,
    drawMarker: false,
    drawPolyline: false,
    drawText: false,
    drawPolygon: true,
    drawRectangle: true,
    drawCircle: true,
    editMode: true,
    dragMode: false,
    cutPolygon: false,
    removalMode: true,
  })
  map.pm.setGlobalOptions({
    continueDrawing: false,
    snappable: true,
    snapDistance: 16,
  })

  map.on('pm:create', (event) => {
    drawnItems.clearLayers()
    drawnItems.addLayer(event.layer)
    emitCurrentSelection()
  })

  map.on('pm:edit', () => {
    emitCurrentSelection()
  })

  map.on('pm:remove', () => {
    emitCurrentSelection()
  })
}

async function syncVisibility() {
  const tasks = props.layers.map(async (layer) => {
    if (props.visibility[layer.id]) {
      try {
        await ensureLayerOnMap(layer)
      } catch (error) {
        console.warn(`Layer "${layer.id}" failed to load:`, error)
      }
    } else {
      removeLayerFromMap(layer.id)
    }
  })

  await Promise.all(tasks)

  if (props.visibility.generatedActivities && layerGroups.has('generatedActivities')) {
    layerGroups.get('generatedActivities').bringToBack()
  }
  if (props.visibility.generatedPopulation && layerGroups.has('generatedPopulation')) {
    layerGroups.get('generatedPopulation').bringToFront()
  }
}

function reloadAllLayers() {
  if (!map) return
  for (const layerId of layerGroups.keys()) {
    removeLayerFromMap(layerId)
  }
  layerGroups.clear()
  syncVisibility()
}

onMounted(async () => {
  map = L.map('resource-map', {
    zoomControl: true,
  }).setView(props.mapView.center, props.mapView.zoom)

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map)

  setupDrawing()
  await syncVisibility()
  emitCurrentSelection()

  await nextTick()
  invalidateMapSize()
  if (mapRootEl.value && typeof ResizeObserver !== 'undefined') {
    mapResizeObserver = new ResizeObserver(() => {
      invalidateMapSize()
    })
    mapResizeObserver.observe(mapRootEl.value)
  }
})

watch(
  () => props.visibility,
  () => {
    syncVisibility()
  },
  { deep: true },
)

watch(
  () => props.layers.map((layer) => `${layer.id}:${layer.url}`).join('|'),
  () => {
    reloadAllLayers()
  },
)

function refreshPublicBikeMarkerPopups() {
  const group = layerGroups.get('bikesharing')
  const layerConfig = props.layers.find((l) => l.id === 'bikesharing')
  if (!group || !layerConfig) return
  group.eachLayer((layer) => {
    if (layer._bikeBaseRow) {
      const merged = mergeBikeRowForDisplay(layer._bikeBaseRow, props.bikeAvailabilityOverrides)
      const html = buildPopup(merged, layerConfig.popupFields)
      if (html) layer.setPopupContent(html)
    }
  })
}

watch(
  () => props.bikeAvailabilityOverrides,
  () => {
    refreshPublicBikeMarkerPopups()
  },
  { deep: true },
)

watch(
  () => props.clearSelectionSignal,
  () => {
    clearSelectionLayers()
  },
)

onBeforeUnmount(() => {
  if (resizeFrame !== null) {
    cancelAnimationFrame(resizeFrame)
    resizeFrame = null
  }
  mapResizeObserver?.disconnect()
  mapResizeObserver = null
  if (map) {
    map.remove()
    map = null
  }
  drawnItems = null
  layerGroups.clear()
})
</script>

<template>
  <div ref="mapRootEl" class="map-root">
    <div id="resource-map" class="map" />
  </div>
</template>

<style scoped>
.map-root {
  flex: 1;
  min-height: 0;
  width: 100%;
  position: relative;
}

.map {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
</style>
