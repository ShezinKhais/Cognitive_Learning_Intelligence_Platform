// Same-origin worklet. Collects mono float samples in memory, never plays them.
class LectureCapture extends AudioWorkletProcessor {
  constructor() {
    super()
    this.samples = new Float32Array(160000)
    this.offset = 0
    this.started = currentTime
  }
  process(inputs) {
    const input = inputs[0]?.[0]
    if (!input) return true
    for (let i = 0; i < input.length; i++) {
      this.samples[this.offset++] = input[i]
      if (this.offset === this.samples.length) {
        this.port.postMessage({ samples: this.samples, started: this.started }, [this.samples.buffer])
        this.samples = new Float32Array(160000)
        this.offset = 0
        this.started = currentTime + (i + 1) / sampleRate
      }
    }
    return true
  }
}
registerProcessor('lecture-capture', LectureCapture)
