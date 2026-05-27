import { reactive } from 'vue'

export function useLayerVisibility(layers) {
  const visibility = reactive(
    layers.reduce((acc, layer) => {
      acc[layer.id] = Boolean(layer.defaultVisible)
      return acc
    }, {}),
  )

  function toggleLayer(layerId) {
    visibility[layerId] = !visibility[layerId]
  }

  return {
    visibility,
    toggleLayer,
  }
}
