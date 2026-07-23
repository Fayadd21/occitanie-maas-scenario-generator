<script setup>
import { onBeforeUnmount, onMounted, ref, computed, watch, nextTick } from 'vue'
import ResourceMap from './components/map/ResourceMap.vue'
import LayerPanel from './components/panels/LayerPanel.vue'
import { DEFAULT_MAP_VIEW, DEFAULT_BASELINE_RUN_ID, RESOURCE_LAYERS, baselineResourceUrl } from './config/layers'
import { useLayerVisibility } from './composables/useLayerVisibility'
import {
  createGenerationJob,
  downloadScenarioExport,
  getConfigDefaults,
  getConfigProfiles,
  getAvailableBaselines,
  getJobStatus,
  getJobOutputs,
  rebuildBaseline,
  setActiveBaseline,
} from './services/jobsApi'
import {
  bikeStationKeyFromRow,
  baseAvailableBikesFromRow,
  clampAvailableBikes,
  effectiveAvailableBikes,
  formatBikeStationName,
  stationCapacityFromRow,
} from './utils/bikeStationKey'

const API_BASE = (import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000').replace(/\/$/, '')

const mapLayers = ref(RESOURCE_LAYERS.map((layer) => ({ ...layer })))
const { visibility, toggleLayer } = useLayerVisibility(mapLayers.value)
const selectionGeoJson = ref(null)
const mapRef = ref(null)
const clearSelectionSignal = ref(0)
const targetPopulation = ref(59_510)
const targetHouseholds = ref(null)
const randomizeEachRun = ref(false)
const userSetTargetHouseholds = ref(false)
const outskirtsBias = ref(0)
const latentClassOptions = ref([])
const allowedLatentClasses = ref([])
const MAX_HOUSEHOLD_SIZE = 6
const BASELINE_TARGET_POPULATION = 59_510
const OCCITANIE_REFERENCE_POPULATION = 5_951_000
const BASELINE_SAMPLING_RATE = BASELINE_TARGET_POPULATION / OCCITANIE_REFERENCE_POPULATION
const jobState = ref({
  status: 'idle',
  jobId: null,
  runId: null,
  jobType: null,
  effectiveConfig: null,
  outputs: [],
  error: null,
  exporting: false,
})
const baselineReady = ref(false)
const baselineRunId = ref(DEFAULT_BASELINE_RUN_ID)
const baselinePopulation = ref(BASELINE_TARGET_POPULATION)
const availableBaselines = ref([])
let pollTimer = null
let outcomeAlertShownForJobId = null

function formatScenarioOutcomeMessage(status) {
  const generatedPersons = status.generated_person_count
  const generatedHouseholds = status.generated_household_count
  if (generatedPersons == null && generatedHouseholds == null) {
    return null
  }

  const lines = ['Scenario generation finished.', '']
  const requestedParts = []
  if (status.requested_target_population != null) {
    requestedParts.push(`${status.requested_target_population} persons`)
  }
  if (status.requested_target_households != null) {
    requestedParts.push(`${status.requested_target_households} households`)
  }
  if (requestedParts.length > 0) {
    lines.push(`Requested: ${requestedParts.join(', ')}`)
  }

  const generatedParts = []
  if (generatedPersons != null) {
    generatedParts.push(`${generatedPersons} persons`)
  }
  if (generatedHouseholds != null) {
    generatedParts.push(`${generatedHouseholds} households`)
  }
  if (generatedParts.length > 0) {
    lines.push(`Generated: ${generatedParts.join(', ')}`)
  }

  if (status.persons_without_requests_count != null) {
    lines.push(`Persons without trip requests: ${status.persons_without_requests_count}`)
  }

  if (status.target_shortfall) {
    lines.push('')
    lines.push(
      'The selection could not supply enough households to reach your targets. ' +
        'All feasible households in the filtered area were kept.',
    )
  }

  return lines.join('\n')
}

function maybeShowScenarioOutcomeAlert(jobId, status) {
  if (status.job_type === 'baseline') {
    return
  }
  const message = formatScenarioOutcomeMessage(status)
  if (!message || outcomeAlertShownForJobId === jobId) {
    return
  }
  window.alert(message)
  outcomeAlertShownForJobId = jobId
}

const bikeAvailabilityOverrides = ref({})
const bikeMapSelection = ref(null)
const bikeEditorDraft = ref('')

const bikeOverlay = computed(() => {
  const row = bikeMapSelection.value?.row
  if (!row) return null
  const key = bikeStationKeyFromRow(row)
  const o = bikeAvailabilityOverrides.value
  const base = baseAvailableBikesFromRow(row)
  const capacity = stationCapacityFromRow(row)
  return {
    key,
    title: formatBikeStationName(row.name) || 'Bike station',
    subId: key || 'No stable station id',
    capacity,
    currentEffective: key ? effectiveAvailableBikes(row, o) : base,
    hasOverride: Boolean(key && Object.prototype.hasOwnProperty.call(o, key)),
    canSave: Boolean(key),
    row,
  }
})

function onBikeStationClick({ row }) {
  if (!row) return
  bikeMapSelection.value = { row }
  const key = bikeStationKeyFromRow(row)
  if (!key) {
    window.alert(
      'This row has no city_station_id and no city_id with station_id, so availability cannot be overridden for the next run.',
    )
  }
  bikeEditorDraft.value = String(effectiveAvailableBikes(row, bikeAvailabilityOverrides.value))
}

function dismissBikeStation() {
  bikeMapSelection.value = null
  bikeEditorDraft.value = ''
}

function setBikeEditorDraft(value) {
  bikeEditorDraft.value = value
}

function applyBikeOverride() {
  const ov = bikeOverlay.value
  if (!ov?.canSave) return
  const raw = Math.round(Number(bikeEditorDraft.value))
  if (!Number.isFinite(raw) || Number.isNaN(raw) || raw < 0) {
    window.alert('Enter a non-negative integer.')
    return
  }
  const n = clampAvailableBikes(raw, ov.capacity)
  if (ov.capacity != null && raw > ov.capacity) {
    window.alert(`Capacity is ${ov.capacity}; availability was capped.`)
  }
  bikeAvailabilityOverrides.value = { ...bikeAvailabilityOverrides.value, [ov.key]: n }
  bikeEditorDraft.value = String(n)
}

function resetBikeOverride() {
  const ov = bikeOverlay.value
  if (!ov?.key || !ov.hasOverride) return
  const { [ov.key]: _removed, ...rest } = bikeAvailabilityOverrides.value
  bikeAvailabilityOverrides.value = rest
  bikeEditorDraft.value = String(baseAvailableBikesFromRow(ov.row))
}

function resetLayersToDefaultOutputs() {
  mapLayers.value = RESOURCE_LAYERS.map((layer) => {
    if (layer.id === 'generatedPopulation' || layer.id === 'generatedActivities') {
      return { ...layer, url: null }
    }
    return { ...layer }
  })
  visibility.generatedPopulation = false
  visibility.generatedActivities = false
}

function refreshLayersForRun(jobId, runId, files) {
  if (!runId || !Array.isArray(files)) return
  const available = new Set(files)
  mapLayers.value = RESOURCE_LAYERS.map((baseLayer) => {
    if (baseLayer.id === 'generatedPopulation') {
      return {
        ...baseLayer,
        url: `${API_BASE}/jobs/${jobId}/population.geojson`,
      }
    }
    if (baseLayer.id === 'generatedActivities') {
      return {
        ...baseLayer,
        url: `${API_BASE}/jobs/${jobId}/activities.geojson`,
      }
    }
    const suffix = baseLayer.outputSuffix
    if (!suffix) {
      return { ...baseLayer }
    }
    const runFile = `${runId}_${suffix}`
    if (!available.has(runFile)) {
      // Keep baseline URL from layers.js when this job did not materialize the layer.
      return { ...baseLayer }
    }
    return {
      ...baseLayer,
      url: `${API_BASE}/resources/jobs/${runId}/${runFile}`,
    }
  })
  visibility.generatedPopulation = true
}

function handleSelectionChange(geojson) {
  selectionGeoJson.value = geojson
  if (!selectionGeoJson.value) {
    outskirtsBias.value = 0
  }
}

function clearSelection() {
  clearSelectionSignal.value += 1
  outskirtsBias.value = 0
}

function handleImportAreaGeoJson(parsed) {
  const result = mapRef.value?.applyImportedGeoJson?.(parsed)
  if (!result?.ok) {
    window.alert(result?.reason || 'Could not import this GeoJSON on the map.')
  }
}

function downloadSelectionGeoJson() {
  const geo = selectionGeoJson.value
  if (!geo || !Array.isArray(geo.features) || geo.features.length === 0) {
    return
  }
  const blob = new Blob([JSON.stringify(geo, null, 2)], { type: 'application/geo+json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'occitanie_generation_area.geojson'
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function setTargetPopulation(value) {
  const numericValue = Number(value)
  if (!Number.isInteger(numericValue) || numericValue <= 0) return
  targetPopulation.value = numericValue
  if (targetHouseholds.value !== null && targetHouseholds.value > targetPopulation.value) {
    targetHouseholds.value = targetPopulation.value
  }
}

function setTargetHouseholds(value) {
  userSetTargetHouseholds.value = true
  if (value === null) {
    targetHouseholds.value = null
    return
  }
  const numericValue = Number(value)
  if (!Number.isInteger(numericValue) || numericValue <= 0) return
  targetHouseholds.value = numericValue
}

function setRandomizeEachRun(value) {
  randomizeEachRun.value = Boolean(value)
}

function setOutskirtsBias(value) {
  if (!Number.isFinite(Number(value))) return
  outskirtsBias.value = Math.max(0, Math.min(1, Number(value)))
}

function setAllowedLatentClasses(values) {
  if (!Array.isArray(values)) return
  const options = new Set(latentClassOptions.value)
  allowedLatentClasses.value = values.filter((value) => options.has(value))
}

function shouldAutoEnableStrictMode() {
  return Number(targetPopulation.value) > Number(baselinePopulation.value)
}

async function refreshBaselineReady() {
  try {
    const defaults = await getConfigDefaults()
    baselineReady.value = Boolean(defaults.baseline_ready)
    if (typeof defaults.baseline_run_id === 'string' && defaults.baseline_run_id.trim()) {
      baselineRunId.value = defaults.baseline_run_id.trim()
    }
    if (Number.isFinite(Number(defaults.baseline_population)) && Number(defaults.baseline_population) > 0) {
      baselinePopulation.value = Math.round(Number(defaults.baseline_population))
    }
    return defaults
  } catch (error) {
    console.warn('Could not load baseline readiness:', error)
    baselineReady.value = false
    return null
  }
}

async function loadBaselines() {
  try {
    const payload = await getAvailableBaselines()
    availableBaselines.value = Array.isArray(payload.baselines) ? payload.baselines : []
    if (typeof payload.baseline_run_id === 'string' && payload.baseline_run_id.trim()) {
      baselineRunId.value = payload.baseline_run_id.trim()
    }
    const active = availableBaselines.value.find((item) => item.active && item.ready)
    if (active) {
      baselineReady.value = true
      if (active.population > 0) {
        baselinePopulation.value = Math.round(Number(active.population))
      }
    }
  } catch (error) {
    console.warn('Could not load baselines:', error)
    availableBaselines.value = []
  }
}

async function selectBaseline(nextBaselineRunId) {
  const nextId = String(nextBaselineRunId || '').trim()
  if (!nextId || nextId === baselineRunId.value) {
    return
  }
  if (jobState.value.status === 'running' || jobState.value.status === 'starting') {
    window.alert('Wait for the current run to finish before switching baseline.')
    return
  }
  try {
    const result = await setActiveBaseline(nextId)
    baselineRunId.value = result.baseline_run_id
    baselineReady.value = Boolean(result.baseline_ready)
    if (Number.isFinite(Number(result.baseline_population)) && Number(result.baseline_population) > 0) {
      baselinePopulation.value = Math.round(Number(result.baseline_population))
    }
    applyBaselineLayerUrls(baselineRunId.value)
    await loadBaselines()
  } catch (error) {
    window.alert(error.message || 'Could not switch baseline.')
    await loadBaselines()
  }
}

function applyBaselineLayerUrls(runId, stamp = Date.now()) {
  const activeRunId = runId || baselineRunId.value || DEFAULT_BASELINE_RUN_ID
  mapLayers.value = RESOURCE_LAYERS.map((layer) => {
    if (layer.id === 'generatedPopulation' || layer.id === 'generatedActivities') {
      return { ...layer, url: null }
    }
    if (!layer.outputSuffix) {
      return { ...layer }
    }
    return {
      ...layer,
      url: `${baselineResourceUrl(layer.outputSuffix, activeRunId)}?v=${stamp}`,
    }
  })
}

async function loadDefaults() {
  try {
    const defaults = await refreshBaselineReady()
    if (!defaults) return
    if (Number.isFinite(Number(defaults.target_population))) {
      targetPopulation.value = Math.max(1, Math.round(Number(defaults.target_population)))
    }
    await loadBaselines()
    applyBaselineLayerUrls(baselineRunId.value)
    userSetTargetHouseholds.value = false
  } catch (error) {
    console.warn('Could not load backend defaults:', error)
  }
}

async function loadProfiles() {
  try {
    const payload = await getConfigProfiles()
    const profileIds = Array.isArray(payload.profiles)
      ? payload.profiles.map((profile) => profile.id)
      : []
    latentClassOptions.value = profileIds
    const defaults = Array.isArray(payload.default_allowed) ? payload.default_allowed : profileIds
    allowedLatentClasses.value = defaults.filter((value) => profileIds.includes(value))
    if (allowedLatentClasses.value.length === 0 && profileIds.length > 0) {
      allowedLatentClasses.value = [...profileIds]
    }
  } catch (error) {
    console.warn('Could not load profile config:', error)
  }
}

function refreshLayersAfterBaselineRebuild() {
  applyBaselineLayerUrls(baselineRunId.value)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function refreshJob(jobId) {
  const status = await getJobStatus(jobId)
  jobState.value.status = status.status
  jobState.value.jobType = status.job_type || null
  jobState.value.effectiveConfig = status.effective_config || null
  if (status.status === 'succeeded' || status.status === 'failed') {
    stopPolling()
    if (status.status === 'succeeded') {
      if (status.job_type === 'baseline') {
        refreshLayersAfterBaselineRebuild()
        await refreshBaselineReady()
        await loadBaselines()
      } else {
        maybeShowScenarioOutcomeAlert(jobId, status)
        const outputs = await getJobOutputs(jobId)
        jobState.value.outputs = outputs.files || []
        refreshLayersForRun(jobId, status.run_id || jobState.value.runId, outputs.files || [])
      }
    }
  }
}

async function startBaselineRebuild() {
  if (targetPopulation.value <= 0 || !Number.isInteger(targetPopulation.value)) {
    window.alert('Target population must be a positive integer.')
    return
  }
  const plannedBaselineId = `baseline_occitanie_${targetPopulation.value}`
  const actionLabel = baselineReady.value ? 'Rebuild' : 'Build'
  const confirmed = window.confirm(
    baselineReady.value
      ? `${actionLabel} baseline as ${plannedBaselineId}? Full synthesis (long) and replaces the current baseline.`
      : `${actionLabel} baseline ${plannedBaselineId}? Full regional synthesis; may take a while.`,
  )
  if (!confirmed) return

  try {
    stopPolling()
    jobState.value = {
      status: 'starting',
      jobId: null,
      runId: null,
      jobType: 'baseline',
      effectiveConfig: null,
      outputs: [],
      error: null,
    }
    const created = await rebuildBaseline(targetPopulation.value)
    jobState.value.jobId = created.job_id
    jobState.value.runId = created.run_id
    jobState.value.status = created.status

    pollTimer = setInterval(() => {
      refreshJob(created.job_id).catch((error) => {
        jobState.value.error = error.message
      })
    }, 3000)

    await refreshJob(created.job_id)
  } catch (error) {
    jobState.value.error = error.message
    jobState.value.status = 'failed'
  }
}

async function startGeneration() {
  if (!baselineReady.value) {
    return
  }
  if (targetPopulation.value <= 0) {
    const message = 'Target population must be greater than 0.'
    window.alert(message)
    jobState.value.error = message
    return
  }
  if (!Number.isInteger(targetPopulation.value)) {
    const message = 'Target population must be an integer.'
    window.alert(message)
    jobState.value.error = message
    return
  }
  if (targetHouseholds.value !== null && targetHouseholds.value <= 0) {
    const message = 'Target households must be greater than 0.'
    window.alert(message)
    jobState.value.error = message
    return
  }
  if (targetHouseholds.value !== null && !Number.isInteger(targetHouseholds.value)) {
    const message = 'Target households must be an integer.'
    window.alert(message)
    jobState.value.error = message
    return
  }
  if (targetHouseholds.value !== null && targetHouseholds.value > targetPopulation.value) {
    const message = 'Target households cannot be greater than target population.'
    window.alert(message)
    jobState.value.error = message
    return
  }
  if (
    targetHouseholds.value !== null &&
    targetPopulation.value > targetHouseholds.value * MAX_HOUSEHOLD_SIZE
  ) {
    const message = `Target population looks incoherent with households. With ${targetHouseholds.value} households and a max household size of ${MAX_HOUSEHOLD_SIZE}, maximum coherent population is ${targetHouseholds.value * MAX_HOUSEHOLD_SIZE}.`
    window.alert(message)
    jobState.value.error = message
    return
  }
  if (!Array.isArray(allowedLatentClasses.value) || allowedLatentClasses.value.length === 0) {
    const message = 'At least one latent class must be selected.'
    window.alert(message)
    jobState.value.error = message
    return
  }

  const requestedTargetPopulation = targetPopulation.value
  const requestedTargetHouseholds = userSetTargetHouseholds.value ? targetHouseholds.value : null
  if (requestedTargetPopulation > baselinePopulation.value) {
    const proceed = window.confirm(
      `Target population (${requestedTargetPopulation}) is larger than the current baseline (${baselinePopulation.value}). ` +
        'A full regional synthesis will run. This can take a long time. Continue?',
    )
    if (!proceed) {
      return
    }
  }

  try {
    stopPolling()
    outcomeAlertShownForJobId = null
    resetLayersToDefaultOutputs()
    jobState.value = {
      status: 'starting',
      jobId: null,
      runId: null,
      jobType: 'scenario',
      effectiveConfig: null,
      outputs: [],
      error: null,
    }
    const strictModeEnabled = shouldAutoEnableStrictMode()
    const samplingRateOverride = strictModeEnabled ? null : BASELINE_SAMPLING_RATE

    const effectiveOutskirtsBias = selectionGeoJson.value ? outskirtsBias.value : 0

    const bikesharingStationAvailability =
      Object.keys(bikeAvailabilityOverrides.value).length > 0 ? { ...bikeAvailabilityOverrides.value } : null

    const created = await createGenerationJob(
      selectionGeoJson.value,
      requestedTargetPopulation,
      requestedTargetHouseholds,
      strictModeEnabled,
      randomizeEachRun.value,
      samplingRateOverride,
      effectiveOutskirtsBias,
      allowedLatentClasses.value,
      null,
      bikesharingStationAvailability,
    )
    jobState.value = {
      status: created.status,
      jobId: created.job_id,
      runId: created.run_id,
      jobType: 'scenario',
      effectiveConfig: null,
      outputs: [],
      error: null,
    }

    pollTimer = setInterval(() => {
      refreshJob(created.job_id).catch((error) => {
        jobState.value.error = error.message
      })
    }, 3000)

    await refreshJob(created.job_id)
  } catch (error) {
    jobState.value.error = error.message
    jobState.value.status = 'failed'
  }
}

async function exportScenario() {
  if (!jobState.value.jobId || jobState.value.status !== 'succeeded' || jobState.value.exporting) {
    return
  }
  jobState.value.exporting = true
  jobState.value.error = null
  try {
    const { blob, filename } = await downloadScenarioExport(jobState.value.jobId)
    const runId = jobState.value.runId || 'scenario'
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename || `${runId}_scenario.zip`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (error) {
    jobState.value.error = error.message || 'Scenario export failed'
  } finally {
    jobState.value.exporting = false
  }
}

watch(
  () => bikeOverlay.value,
  async () => {
    await nextTick()
    requestAnimationFrame(() => {
      mapRef.value?.invalidateMapSize?.()
    })
  },
)

onBeforeUnmount(() => {
  stopPolling()
})

onMounted(() => {
  loadDefaults()
  loadProfiles()
})
</script>

<template>
  <main class="layout">
    <LayerPanel
      :layers="mapLayers"
      :job-state="jobState"
      :baseline-ready="baselineReady"
      :baseline-run-id="baselineRunId"
      :available-baselines="availableBaselines"
      :selection-geo-json="selectionGeoJson"
      :target-population="targetPopulation"
      :target-households="targetHouseholds"
      :randomize-each-run="randomizeEachRun"
      :outskirts-bias="outskirtsBias"
      :has-selection="Boolean(selectionGeoJson)"
      :latent-class-options="latentClassOptions"
      :allowed-latent-classes="allowedLatentClasses"
      :bike-overlay="bikeOverlay"
      :bike-editor-draft="bikeEditorDraft"
      :visibility="visibility"
      @clear-selection="clearSelection"
      @start-generation="startGeneration"
      @rebuild-baseline="startBaselineRebuild"
      @select-baseline="selectBaseline"
      @export-scenario="exportScenario"
      @update:target-population="setTargetPopulation"
      @update:target-households="setTargetHouseholds"
      @update:randomize-each-run="setRandomizeEachRun"
      @update:outskirts-bias="setOutskirtsBias"
      @update:allowed-latent-classes="setAllowedLatentClasses"
      @update:bike-editor-draft="setBikeEditorDraft"
      @dismiss-bike-station="dismissBikeStation"
      @apply-bike-override="applyBikeOverride"
      @reset-bike-override="resetBikeOverride"
      @toggle="toggleLayer"
      @import-area-geojson="handleImportAreaGeoJson"
      @download-selection-geojson="downloadSelectionGeoJson"
    />

    <section class="map-wrap">
      <ResourceMap
        ref="mapRef"
        :layers="mapLayers"
        :map-view="DEFAULT_MAP_VIEW"
        :visibility="visibility"
        :clear-selection-signal="clearSelectionSignal"
        :bike-availability-overrides="bikeAvailabilityOverrides"
        @selection-change="handleSelectionChange"
        @bike-station-click="onBikeStationClick"
      />
    </section>
  </main>
</template>
