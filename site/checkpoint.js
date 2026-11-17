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
