import { useEffect, useRef } from 'react'

import { coveredWindowSeconds, summary } from './signals'
import type { AttentionSummary, FaceObservation } from './signals'
import type { SensorSamples } from './useLocalSensor'

/** Sending has its own clock, independent of the consent-verification request. */
export function useAttentionReporter(
  enabled: boolean,
  cameraActive: () => boolean,
  cameraStartedAt: () => number,
  drainCamera: () => SensorSamples<FaceObservation>,
  microphoneActive: () => boolean,
  microphoneStartedAt: () => number,
  drainMicrophone: () => SensorSamples<boolean | null>,
  onSignal: (value: AttentionSummary) => boolean,
  onRefused: () => void,
) {
  const emit = useRef(onSignal)
  emit.current = onSignal
  const refused = useRef(onRefused)
  refused.current = onRefused

  useEffect(() => {
    if (!enabled) return
    let last = performance.now()
    const timer = setInterval(() => {
      if (!cameraActive() && !microphoneActive()) {
        last = performance.now()
        return
      }
      const now = performance.now()
      const started = [cameraActive() ? cameraStartedAt() : 0, microphoneActive() ? microphoneStartedAt() : 0]
        .filter(value => value > 0)
      const face = drainCamera()
      const voice = drainMicrophone()
      const payload = summary(
        cameraActive() ? face.values : [],
        microphoneActive() ? voice.values.filter((value): value is boolean => value !== null) : [],
        coveredWindowSeconds(now, last, started),
        { now, faceAt: face.latestAt, speechAt: voice.latestAt },
      )
      last = now
      if (!document.hidden && !emit.current(payload)) refused.current()
    }, 5000)
    return () => clearInterval(timer)
  }, [enabled, cameraActive, cameraStartedAt, drainCamera, microphoneActive, microphoneStartedAt, drainMicrophone])
}
