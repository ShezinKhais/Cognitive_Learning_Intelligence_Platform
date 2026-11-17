const sample = document.querySelector('#sample')
const feedback = document.querySelector('#sample-feedback')

sample.addEventListener('submit', (event) => {
  event.preventDefault()
  const answer = new FormData(sample).get('planet')
  feedback.textContent = answer === 'Jupiter'
    ? 'Correct. Jupiter is the largest planet in the Solar System.'
    : 'Revisit planet size. Jupiter is the largest planet in the Solar System.'
})

sample.addEventListener('change', () => {
  feedback.textContent = ''
})

const readings = {
  facing: {
    title: 'Face detected · likely facing the screen',
    detail: 'The camera estimate describes direction. It cannot tell whether the student understands the lesson.',
  },
  away: {
    title: 'Face detected · looking aside',
    detail: 'The student may be reading notes or using another screen. This reading alone does not trigger a refocus prompt.',
  },
  unavailable: {
    title: 'Gaze reading unavailable',
    detail: 'If the camera is off or the browser cannot get a clear reading, students can still answer checkpoints and use the lesson tools.',
  },
}

const readingChoices = document.querySelectorAll('[data-reading]')
const signalTitle = document.querySelector('#signal-title')
const signalDetail = document.querySelector('#signal-detail')

for (const choice of readingChoices) {
  choice.addEventListener('click', () => {
    const reading = readings[choice.dataset.reading]
    signalTitle.textContent = reading.title
    signalDetail.textContent = reading.detail

    for (const option of readingChoices) {
      option.setAttribute('aria-pressed', String(option === choice))
    }
  })
}
