const API_BASE = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'

export async function getConfigDefaults() {
  const response = await fetch(`${API_BASE}/config/defaults`)
  if (!response.ok) {
    throw new Error(`Config defaults failed: ${response.status}`)
  }
  return response.json()
}

export async function getConfigProfiles() {
  const response = await fetch(`${API_BASE}/config/profiles`)
  if (!response.ok) {
    throw new Error(`Config profiles failed: ${response.status}`)
  }
  return response.json()
}

export async function getAvailableBaselines() {
  const response = await fetch(`${API_BASE}/config/baselines`)
  if (!response.ok) {
    throw new Error(`Baseline list failed: ${response.status}`)
  }
  return response.json()
}

export async function setActiveBaseline(baselineRunId) {
  const response = await fetch(`${API_BASE}/config/baseline`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ baseline_run_id: baselineRunId }),
  })
  if (!response.ok) {
    let detail = `Baseline selection failed: ${response.status}`
    try {
      const payload = await response.json()
      if (payload?.detail) {
        detail = typeof payload.detail === 'string' ? payload.detail : detail
      }
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return response.json()
}

export async function rebuildBaseline(targetPopulation) {
  const body =
    targetPopulation !== null && targetPopulation !== undefined && Number.isFinite(Number(targetPopulation))
      ? { target_population: Math.round(Number(targetPopulation)) }
      : {}
  const response = await fetch(`${API_BASE}/baseline/rebuild`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(`Baseline rebuild failed: ${response.status}`)
  }
  return response.json()
}

export async function createGenerationJob(
  selectedAreaGeoJson,
  targetPopulation,
  targetHouseholds = null,
  strictTargetMode = false,
  randomizeEachRun = false,
  samplingRateOverride = null,
  outskirtsBias = 0,
  allowedLatentClasses = null,
  extraConfigOverrides = null,
  bikesharingStationAvailability = null,
) {
  const configOverrides = {
    strict_target_mode: strictTargetMode,
    randomize_each_run: randomizeEachRun,
    ...(extraConfigOverrides && typeof extraConfigOverrides === 'object' ? extraConfigOverrides : {}),
  }
  if (
    samplingRateOverride !== null &&
    samplingRateOverride !== undefined &&
    Number.isFinite(Number(samplingRateOverride))
  ) {
    configOverrides.sampling_rate = Number(samplingRateOverride)
  }
  if (Number.isFinite(Number(outskirtsBias))) {
    configOverrides.outskirts_bias = Math.max(0, Math.min(1, Number(outskirtsBias)))
  }
  if (Array.isArray(allowedLatentClasses) && allowedLatentClasses.length > 0) {
    configOverrides.allowed_latent_classes = allowedLatentClasses
  }

  const response = await fetch(`${API_BASE}/jobs`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      selected_area_geojson: selectedAreaGeoJson || null,
      target_population: targetPopulation || null,
      target_households: targetHouseholds || null,
      config_overrides: configOverrides,
      bikesharing_station_availability:
        bikesharingStationAvailability && typeof bikesharingStationAvailability === 'object'
          ? bikesharingStationAvailability
          : {},
    }),
  })

  if (!response.ok) {
    throw new Error(`Job creation failed: ${response.status}`)
  }
  return response.json()
}

export async function getJobStatus(jobId) {
  const response = await fetch(`${API_BASE}/jobs/${jobId}`)
  if (!response.ok) {
    throw new Error(`Job status failed: ${response.status}`)
  }
  return response.json()
}

export async function getJobOutputs(jobId) {
  const response = await fetch(`${API_BASE}/jobs/${jobId}/outputs`)
  if (!response.ok) {
    throw new Error(`Job outputs failed: ${response.status}`)
  }
  return response.json()
}

export async function downloadScenarioExport(jobId) {
  const response = await fetch(`${API_BASE}/jobs/${jobId}/scenario.json`)
  if (!response.ok) {
    throw new Error(`Scenario export failed: ${response.status}`)
  }
  return response.json()
}
