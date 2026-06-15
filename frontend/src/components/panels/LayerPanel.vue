<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  layers: {
    type: Array,
    required: true,
  },
  visibility: {
    type: Object,
    required: true,
  },
  selectionGeoJson: {
    type: Object,
    default: null,
  },
  jobState: {
    type: Object,
    required: true,
  },
  baselineReady: {
    type: Boolean,
    default: false,
  },
  baselineRunId: {
    type: String,
    default: '',
  },
  targetPopulation: {
    type: Number,
    required: true,
  },
  targetHouseholds: {
    type: Number,
    default: null,
  },
  randomizeEachRun: {
    type: Boolean,
    default: false,
  },
  outskirtsBias: {
    type: Number,
    default: 0,
  },
  hasSelection: {
    type: Boolean,
    default: false,
  },
  latentClassOptions: {
    type: Array,
    default: () => [],
  },
  allowedLatentClasses: {
    type: Array,
    default: () => [],
  },
  bikeOverlay: {
    type: Object,
    default: null,
  },
  bikeEditorDraft: {
    type: String,
    default: '',
  },
})

const jobBusy = computed(
  () => props.jobState.status === 'running' || props.jobState.status === 'starting',
)

const generateDisabled = computed(() => !props.baselineReady || jobBusy.value)

const STATUS_LABELS = {
  idle: 'Idle',
  starting: 'Starting',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
}

const statusLabel = computed(
  () => STATUS_LABELS[props.jobState.status] || props.jobState.status,
)

const statusBadgeClass = computed(() => {
  const status = props.jobState.status
  if (status === 'succeeded') return 'status-badge status-badge--success'
  if (status === 'failed') return 'status-badge status-badge--error'
  if (status === 'running' || status === 'starting') return 'status-badge status-badge--running'
  return 'status-badge status-badge--neutral'
})

const isBaselineJob = computed(() => {
  const config = props.jobState.effectiveConfig
  return props.jobState.jobType === 'baseline' || config?.job_type === 'baseline'
})

const baselineActionLabel = computed(() => (props.baselineReady ? 'Rebuild baseline' : 'Build baseline'))

const baselineActionHint = computed(() =>
  props.baselineReady
    ? 'Rebuild from target population (creates baseline_occitanie_N).'
    : 'Build from target population before generating scenarios.',
)

function formatSamplingRate(value) {
  const rate = Number(value)
  if (!Number.isFinite(rate)) return value
  if (rate >= 0.001) return String(rate)
  return rate.toExponential(3)
}

const effectiveRows = computed(() => {
  const config = props.jobState.effectiveConfig
  if (!config) return []
  const rows = []
  if (isBaselineJob.value) {
    if (config.baseline_run_id) {
      rows.push({ label: 'Baseline', value: config.baseline_run_id })
    }
  } else {
    rows.push({
      label: 'Population source',
      value: config.population_source === 'full_synthesis' ? 'full synthesis' : 'baseline',
    })
  }
  if (config.sampling_rate != null) {
    rows.push({ label: 'Sampling', value: formatSamplingRate(config.sampling_rate) })
  }
  if (!isBaselineJob.value) {
    rows.push({
      label: 'Random seed',
      value: config.randomize_each_run ? 'yes' : 'no',
    })
  }
  return rows
})

const copiedRunId = ref(false)

async function copyRunId() {
  if (!props.jobState.runId) return
  try {
    await navigator.clipboard.writeText(props.jobState.runId)
    copiedRunId.value = true
    window.setTimeout(() => {
      copiedRunId.value = false
    }, 2000)
  } catch {
    // Clipboard may be unavailable outside a secure context.
  }
}

const emit = defineEmits([
  'toggle',
  'clearSelection',
  'startGeneration',
  'rebuildBaseline',
  'exportScenario',
  'importAreaGeojson',
  'downloadSelectionGeojson',
  'update:target-population',
  'update:target-households',
  'update:randomize-each-run',
  'update:outskirts-bias',
  'update:allowed-latent-classes',
  'update:bike-editor-draft',
  'dismiss-bike-station',
  'apply-bike-override',
  'reset-bike-override',
])

const importGeoJsonInput = ref(null)

const visibleLayerCount = computed(
  () => props.layers.filter((layer) => props.visibility[layer.id]).length,
)

function triggerImportGeoJson() {
  importGeoJsonInput.value?.click()
}

function onImportGeoJsonSelected(event) {
  const input = event.target
  const file = input.files && input.files[0]
  input.value = ''
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const parsed = JSON.parse(String(reader.result || ''))
      emit('importAreaGeojson', parsed)
    } catch {
      window.alert('The file is not valid JSON.')
    }
  }
  reader.onerror = () => {
    window.alert('Could not read the file.')
  }
  reader.readAsText(file, 'utf-8')
}

function downloadSelection() {
  emit('downloadSelectionGeojson')
}

function updateTargetPopulation(event) {
  const raw = String(event.target.value ?? '').trim()
  if (!/^\d+$/.test(raw)) {
    event.target.value = String(props.targetPopulation ?? '')
    return
  }
  const value = Number(raw)
  if (!Number.isInteger(value) || value <= 0) {
    event.target.value = String(props.targetPopulation ?? '')
    return
  }
  emit('update:target-population', value)
}

function updateTargetHouseholds(event) {
  const raw = String(event.target.value ?? '').trim()
  if (raw === '' || raw === null) {
    emit('update:target-households', null)
    return
  }
  if (!/^\d+$/.test(raw)) {
    event.target.value = props.targetHouseholds === null ? '' : String(props.targetHouseholds)
    return
  }
  const value = Number(raw)
  if (!Number.isInteger(value) || value <= 0) {
    event.target.value = props.targetHouseholds === null ? '' : String(props.targetHouseholds)
    return
  }
  emit('update:target-households', value)
}

function preventNonIntegerInput(event) {
  if (event.ctrlKey || event.metaKey || event.altKey) return
  const blockedKeys = ['.', ',', 'e', 'E', '-', '+']
  if (blockedKeys.includes(event.key)) {
    event.preventDefault()
  }
}

function preventNonIntegerBeforeInput(event) {
  const data = event.data ?? ''
  if (data && /[^0-9]/.test(data)) {
    event.preventDefault()
  }
}

function preventNonIntegerPaste(event) {
  const text = event.clipboardData?.getData('text') ?? ''
  if (!/^\d+$/.test(text.trim())) {
    event.preventDefault()
  }
}

function preventNonIntegerDrop(event) {
  const text = event.dataTransfer?.getData('text') ?? ''
  if (!/^\d+$/.test(text.trim())) {
    event.preventDefault()
  }
}

function updateRandomizeEachRun(event) {
  emit('update:randomize-each-run', Boolean(event.target.checked))
}

function updateOutskirtsBias(event) {
  const value = Number(event.target.value)
  if (!Number.isFinite(value)) return
  emit('update:outskirts-bias', value)
}

function toggleLatentClass(latentClass, checked) {
  const current = new Set(props.allowedLatentClasses || [])
  if (checked) current.add(latentClass)
  else {
    if (current.size <= 1 && current.has(latentClass)) return
    current.delete(latentClass)
  }
  emit('update:allowed-latent-classes', Array.from(current))
}

function onBikeEditorInput(event) {
  emit('update:bike-editor-draft', String(event.target.value ?? ''))
}
</script>

<template>
  <aside class="panel">
    <div class="panel-scroll">
    <header class="panel-heading">
      <h1>Occitanie MaaS Scenario Generator</h1>
    </header>

    <div class="layers-field">
      <details class="latent-details">
        <summary class="latent-summary">
          <span>Resource layers</span>
          <span class="latent-summary-count">{{ visibleLayerCount }}/{{ layers.length }}</span>
        </summary>
        <div class="latent-body">
          <ul class="layer-list">
            <li v-for="layer in layers" :key="layer.id">
              <label class="layer-row">
                <input
                  :checked="visibility[layer.id]"
                  class="layer-check"
                  type="checkbox"
                  @change="emit('toggle', layer.id)"
                />
                <span class="layer-label">{{ layer.label }}</span>
              </label>
            </li>
          </ul>
        </div>
      </details>
    </div>

    <section v-if="bikeOverlay" class="bike-station-panel">
      <p class="subtitle">Bike station</p>
      <p class="selection-state bike-title">{{ bikeOverlay.title }}</p>
      <p class="selection-state bike-id">{{ bikeOverlay.subId }}</p>
      <p v-if="bikeOverlay.capacity != null" class="selection-state">
        Capacity: <strong>{{ bikeOverlay.capacity }}</strong>
      </p>
      <p class="selection-state">
        Available bikes: <strong>{{ bikeOverlay.currentEffective }}</strong>
        <span v-if="bikeOverlay.hasOverride" class="muted"> · override</span>
      </p>
      <label class="target-input-wrap">
        <span>Set for next generation run</span>
        <input
          class="target-input"
          min="0"
          :max="bikeOverlay.capacity != null ? bikeOverlay.capacity : undefined"
          step="1"
          type="number"
          :value="bikeEditorDraft"
          @input="onBikeEditorInput"
        />
      </label>
      <button
        class="clear-btn import-btn"
        type="button"
        :disabled="!bikeOverlay.canSave"
        @click="emit('apply-bike-override')"
      >
        Save override
      </button>
      <button
        v-if="bikeOverlay.hasOverride"
        class="clear-btn"
        type="button"
        @click="emit('reset-bike-override')"
      >
        Clear override
      </button>
      <button class="clear-btn" type="button" @click="emit('dismiss-bike-station')">Close</button>
    </section>

    <section class="selection panel-block">
      <p class="subtitle">Generation area</p>
      <p v-if="selectionGeoJson" class="selection-state">
        Custom area selected
      </p>
      <p v-else class="selection-state">
        No area selected (full Occitanie will be used)
      </p>
      <label class="target-input-wrap">
        <span>Target population</span>
        <input
          class="target-input"
          min="1"
          step="1"
          type="number"
          inputmode="numeric"
          :value="targetPopulation"
          @keydown="preventNonIntegerInput"
          @beforeinput="preventNonIntegerBeforeInput"
          @paste="preventNonIntegerPaste"
          @drop="preventNonIntegerDrop"
          @input="updateTargetPopulation"
        />
      </label>

      <label class="target-input-wrap">
        <span>Target households</span>
        <input
          class="target-input"
          min="1"
          step="1"
          type="number"
          inputmode="numeric"
          :value="targetHouseholds ?? ''"
          @keydown="preventNonIntegerInput"
          @beforeinput="preventNonIntegerBeforeInput"
          @paste="preventNonIntegerPaste"
          @drop="preventNonIntegerDrop"
          @input="updateTargetHouseholds"
        />
      </label>

      <label class="target-input-wrap checkbox-wrap">
        <span>New Random Seed Each Run</span>
        <input type="checkbox" :checked="randomizeEachRun" @change="updateRandomizeEachRun" />
      </label>

      <label class="target-input-wrap">
        <span>Outskirts bias</span>
        <input
          class="target-input slider-input"
          min="0"
          max="1"
          step="0.05"
          type="range"
          :value="outskirtsBias"
          :disabled="!hasSelection"
          @input="updateOutskirtsBias"
        />
        <span class="bias-value">
          Current: {{ Number(outskirtsBias).toFixed(2) }}
          <span v-if="!hasSelection" class="muted"> · select an area to enable</span>
        </span>
        <p v-if="hasSelection" class="latent-help">
          Prefer households near the polygon edge. Lower values spread selection more randomly.
        </p>
      </label>

      <div class="latent-field">
        <details class="latent-details">
          <summary class="latent-summary">
            <span>Allowed latent classes</span>
            <span class="latent-summary-count">{{ allowedLatentClasses.length }}/{{ latentClassOptions.length }}</span>
          </summary>
          <div class="latent-body">
            <p class="latent-help">Uncheck classes you want to exclude from the next run.</p>
            <label
              v-for="latentClass in latentClassOptions"
              :key="latentClass"
              class="latent-option"
            >
              <input
                type="checkbox"
                :checked="allowedLatentClasses.includes(latentClass)"
                :disabled="allowedLatentClasses.length === 1 && allowedLatentClasses.includes(latentClass)"
                @change="(event) => toggleLatentClass(latentClass, event.target.checked)"
              />
              <span>{{ latentClass }}</span>
            </label>
          </div>
        </details>
      </div>
    </section>

    <div class="panel-actions">
      <input
        ref="importGeoJsonInput"
        accept=".geojson,.json,application/geo+json"
        class="sr-only"
        type="file"
        @change="onImportGeoJsonSelected"
      />
      <button
        class="clear-btn"
        :disabled="!selectionGeoJson"
        type="button"
        @click="emit('clearSelection')"
      >
        Clear selected area
      </button>
      <button class="clear-btn" type="button" @click="triggerImportGeoJson">Import area GeoJSON</button>
      <button
        class="clear-btn"
        :disabled="!selectionGeoJson"
        type="button"
        @click="downloadSelection"
      >
        Export area GeoJSON
      </button>
      <p v-if="!baselineReady" class="selection-state baseline-hint">
        Run <strong>Build baseline</strong> before generating a scenario population.
      </p>
      <p v-else-if="baselineRunId" class="selection-state">
        Active baseline: <strong class="job-log-mono">{{ baselineRunId }}</strong>
      </p>
      <button
        class="generate-btn"
        :disabled="generateDisabled"
        :title="
          baselineReady
            ? 'Generate population for the selected area'
            : 'Baseline is missing or incomplete - build baseline first'
        "
        type="button"
        @click="emit('startGeneration')"
      >
        Generate population
      </button>
      <button
        class="clear-btn"
        :disabled="jobBusy"
        :title="baselineActionHint"
        type="button"
        @click="emit('rebuildBaseline')"
      >
        {{ baselineActionLabel }}
      </button>
      <button
        class="clear-btn"
        :disabled="jobState.status !== 'succeeded' || !jobState.jobId"
        type="button"
        @click="emit('exportScenario')"
      >
        Export scenario JSON
      </button>
    </div>

    <section class="panel-job-log panel-block" aria-label="Run status and logs">
      <div class="job-log-header">
        <p class="subtitle job-log-title">Run status</p>
        <span
          v-if="jobState.status !== 'idle'"
          :class="statusBadgeClass"
          :aria-label="`Status: ${statusLabel}`"
        >
          <span v-if="jobBusy" class="status-spinner" aria-hidden="true" />
          {{ statusLabel }}
        </span>
      </div>

      <p v-if="jobState.status === 'idle' && !jobState.error" class="job-log-empty">
        No run yet. Build a baseline or start a scenario generation to see progress here.
      </p>

      <dl v-else class="job-log-details">
        <template v-if="jobState.runId">
          <dt>Run ID</dt>
          <dd class="job-log-mono">
            <span class="job-log-run-id" :title="jobState.runId">{{ jobState.runId }}</span>
            <button type="button" class="job-log-copy" @click="copyRunId">
              {{ copiedRunId ? 'Copied' : 'Copy' }}
            </button>
          </dd>
        </template>
        <template v-for="row in effectiveRows" :key="row.label">
          <dt>{{ row.label }}</dt>
          <dd>{{ row.value }}</dd>
        </template>
        <template v-if="jobState.outputs && jobState.outputs.length">
          <dt>Outputs</dt>
          <dd>{{ jobState.outputs.length }} files</dd>
        </template>
        <template v-if="jobState.error">
          <dt>Error</dt>
          <dd class="job-log-error">{{ jobState.error }}</dd>
        </template>
      </dl>
    </section>
    </div>
  </aside>
</template>

<style scoped>
.panel {
  --ink: #0f172a;
  --muted: #64748b;
  --line: #e2e8f0;
  --surface: #f8fafc;
  width: 320px;
  flex-shrink: 0;
  height: 100%;
  max-height: 100%;
  min-height: 0;
  align-self: stretch;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--line);
  box-sizing: border-box;
  background: #fff;
  overflow: hidden;
  color: var(--ink);
  font-size: 14px;
  line-height: 1.45;
}

.panel-scroll {
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: scroll;
  scrollbar-gutter: stable;
  padding: 18px 16px 20px;
  box-sizing: border-box;
}

@media (max-width: 900px) {
  .panel {
    width: 100%;
    border-right: none;
    border-bottom: 1px solid var(--line);
    max-height: 40dvh;
  }
}

.panel-heading {
  margin-bottom: 12px;
  text-align: center;
}

h1 {
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.02em;
  margin: 0;
  line-height: 1.25;
  color: var(--ink);
}

.subtitle {
  margin: 0 0 12px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 500;
}

.panel-heading .subtitle {
  margin-bottom: 10px;
}

.layers-field {
  margin-bottom: 4px;
}

.latent-body .layer-list {
  margin: 8px 0 0;
  padding: 0;
}

.layer-list {
  list-style: none;
  margin: 0 0 4px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.layer-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 13px;
  line-height: 1.35;
  color: #334155;
  padding: 8px 10px;
  margin: 0 -4px;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 0.12s ease;
}

.layer-row:hover {
  background: var(--surface);
}

.layer-row:has(.layer-check:checked) {
  background: #f1f5f9;
  color: var(--ink);
}

.layer-check {
  margin: 2px 0 0;
  width: 15px;
  height: 15px;
  flex-shrink: 0;
  accent-color: #1e40af;
  cursor: pointer;
}

.layer-label {
  flex: 1;
  min-width: 0;
}

.panel-block {
  margin-top: 16px;
  padding: 14px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
}

.panel-block .subtitle {
  margin-top: 0;
  margin-bottom: 10px;
  color: #475569;
}

input {
  margin: 0;
}

.selection-state.muted,
.muted {
  color: #9ca3af;
  font-size: 12px;
}

.bike-station-panel {
  margin-top: 14px;
  padding: 14px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
}

.bike-station-panel .subtitle {
  margin-bottom: 8px;
}

.bike-title {
  font-weight: 600;
  color: var(--ink);
}

.bike-id {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  word-break: break-all;
}

.selection.panel-block {
  background: #fff;
}

.selection-state {
  margin: 0 0 10px;
  font-size: 13px;
  color: #475569;
}

.selection .selection-state:first-of-type {
  font-weight: 500;
  color: var(--ink);
}

.clear-btn {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  padding: 9px 12px;
  font-size: 13px;
  cursor: pointer;
  margin-top: 8px;
  color: #334155;
  transition: background-color 0.12s ease, border-color 0.12s ease;
}

.clear-btn:hover:not(:disabled) {
  background: var(--surface);
  border-color: #cbd5e1;
}

.clear-btn:focus-visible {
  outline: 2px solid #93c5fd;
  outline-offset: 2px;
}

.clear-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.panel-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}

.panel-actions .clear-btn,
.panel-actions .generate-btn {
  margin-top: 0;
}

.panel-job-log {
  margin-top: 16px;
}

.panel-job-log .job-log-title {
  margin: 0;
}

.job-log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}

.job-log-empty {
  margin: 0;
  font-size: 13px;
  color: var(--muted);
  line-height: 1.45;
}

.job-log-details {
  margin: 0;
  display: grid;
  grid-template-columns: minmax(0, 38%) 1fr;
  gap: 6px 12px;
  font-size: 13px;
}

.job-log-details dt {
  margin: 0;
  color: var(--muted);
  font-weight: 500;
}

.job-log-details dd {
  margin: 0;
  color: var(--ink);
  min-width: 0;
  word-break: break-word;
}

.job-log-mono {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.job-log-run-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  line-height: 1.4;
  flex: 1;
  min-width: 0;
  word-break: break-all;
}

.job-log-copy {
  flex-shrink: 0;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  padding: 2px 8px;
  font-size: 11px;
  color: #475569;
  cursor: pointer;
}

.job-log-copy:hover {
  background: var(--surface);
  border-color: #cbd5e1;
}

.job-log-error {
  color: #b91c1c;
  font-size: 12px;
  line-height: 1.4;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  white-space: nowrap;
}

.status-badge--neutral {
  background: #f1f5f9;
  color: #475569;
}

.status-badge--running {
  background: #dbeafe;
  color: #1d4ed8;
}

.status-badge--success {
  background: #dcfce7;
  color: #15803d;
}

.status-badge--error {
  background: #fee2e2;
  color: #b91c1c;
}

.status-spinner {
  width: 10px;
  height: 10px;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: job-status-spin 0.7s linear infinite;
}

@keyframes job-status-spin {
  to {
    transform: rotate(360deg);
  }
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.generate-btn {
  width: 100%;
  margin-top: 10px;
  border: 1px solid var(--ink);
  border-radius: 8px;
  background: var(--ink);
  color: #fff;
  padding: 10px 12px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.12s ease, background-color 0.12s ease;
}

.generate-btn:hover:not(:disabled) {
  background: #1e293b;
  border-color: #1e293b;
}

.generate-btn:focus-visible {
  outline: 2px solid #93c5fd;
  outline-offset: 2px;
}

.generate-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error {
  color: #b91c1c;
}

.baseline-hint {
  margin: 0 0 8px;
  line-height: 1.4;
}

.target-input-wrap {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
  margin-top: 10px;
  font-size: 13px;
  color: #334155;
}

.target-input {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 11px;
  font-size: 13px;
  min-height: 38px;
  box-sizing: border-box;
  background: #fff;
  color: var(--ink);
  transition: border-color 0.12s ease, box-shadow 0.12s ease;
}

.target-input:hover:not(:disabled) {
  border-color: #cbd5e1;
}

.target-input:focus {
  outline: none;
}

.target-input:focus-visible {
  border-color: #64748b;
  box-shadow: 0 0 0 3px rgba(148, 163, 184, 0.35);
}

.checkbox-wrap {
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
}

.checkbox-wrap input[type='checkbox'] {
  width: 15px;
  height: 15px;
  accent-color: #1e40af;
  cursor: pointer;
}

.latent-field {
  margin-top: 10px;
}

.latent-details {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}

.latent-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  list-style-position: outside;
  user-select: none;
}

.latent-summary::-webkit-details-marker {
  color: #6b7280;
}

.latent-summary-count {
  font-size: 12px;
  font-weight: 400;
  font-variant-numeric: tabular-nums;
  color: #6b7280;
}

.latent-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 0 10px 12px 12px;
  border-top: 1px solid var(--line);
  background: #fafafa;
}

.latent-help {
  margin: 8px 0 4px;
  font-size: 12px;
  line-height: 1.35;
  color: #6b7280;
}

.latent-option {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  box-sizing: border-box;
  padding: 7px 8px;
  margin: 0;
  border-radius: 6px;
  font-size: 13px;
  color: #334155;
  cursor: pointer;
  line-height: 1.35;
}

.latent-option:hover {
  background: rgba(255, 255, 255, 0.8);
}

.latent-option input[type='checkbox'] {
  flex-shrink: 0;
  width: 15px;
  height: 15px;
  margin: 2px 0 0;
  accent-color: #1e40af;
  cursor: pointer;
}

.latent-option span {
  flex: 1;
  min-width: 0;
  word-break: break-word;
}

.slider-input {
  padding: 0;
  height: 6px;
  accent-color: #1e40af;
  cursor: pointer;
}

.bias-value {
  margin: 0;
  font-size: 12px;
  color: #4b5563;
}
</style>
