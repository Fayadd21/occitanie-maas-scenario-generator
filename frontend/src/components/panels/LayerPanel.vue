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
        <span>Randomize each run</span>
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
          Share of the population target taken from homes nearest the polygon edge; the rest is random.
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
        Run <strong>Rebuild baseline</strong> before generating a scenario population.
      </p>
      <button
        class="generate-btn"
        :disabled="generateDisabled"
        :title="
          baselineReady
            ? 'Generate population for the selected area'
            : 'Baseline is missing or incomplete — rebuild baseline first'
        "
        type="button"
        @click="emit('startGeneration')"
      >
        Generate population
      </button>
      <button
        class="clear-btn"
        :disabled="jobBusy"
        type="button"
        @click="emit('rebuildBaseline')"
      >
        Rebuild baseline
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

    <section class="panel-job-log" aria-label="Run status and logs">
      <p class="subtitle job-log-title">Run status</p>
      <p class="selection-state" v-if="jobState.status !== 'idle'">
        Status: {{ jobState.status }}
      </p>
      <p class="selection-state" v-if="jobState.runId">
        Run: {{ jobState.runId }}
      </p>
      <p class="selection-state" v-if="jobState.cacheSource">
        Cache source: {{ jobState.cacheSource }}
      </p>
      <p class="selection-state" v-if="jobState.effectiveConfig">
        Effective: sampling={{ jobState.effectiveConfig.sampling_rate }}, strict={{ jobState.effectiveConfig.strict_target_mode }}, random={{ jobState.effectiveConfig.randomize_each_run }}
      </p>
      <p class="selection-state error" v-if="jobState.error">
        Error: {{ jobState.error }}
      </p>
      <p class="selection-state" v-if="jobState.outputs && jobState.outputs.length">
        Outputs: {{ jobState.outputs.length }} files
      </p>
    </section>
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
  border-right: 1px solid var(--line);
  padding: 18px 16px 20px;
  box-sizing: border-box;
  background: #fff;
  overflow: auto;
  overflow-x: hidden;
  color: var(--ink);
  font-size: 14px;
  line-height: 1.45;
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
  padding-top: 14px;
  border-top: 1px solid var(--line);
}

.panel-job-log .job-log-title {
  margin-bottom: 8px;
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
