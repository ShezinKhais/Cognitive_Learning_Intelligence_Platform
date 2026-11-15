/**
 * The paperclip: in the Teams side panel C.L.I.P rests as one small clip and
 * opens up to the student's score and questions, so it is not on screen all
 * the time. These are the words and the rule for when it opens by itself.
 */

/** What the closed clip says: the student's own checkpoints, and a question waiting. */
export function paperclipLabel(answered: number, delivered: number, questionOpen: boolean): string {
  const score = delivered > 0 ? `${answered} of ${delivered} checkpoints answered` : 'No checkpoints yet'
  return questionOpen ? `C.L.I.P. A question is waiting. ${score}.` : `C.L.I.P. ${score}.`
}

/** The short text beside the clip, empty until there is something to show. */
export function paperclipScore(answered: number, delivered: number): string {
  return delivered > 0 ? `${answered}/${delivered}` : ''
}

/**
 * The clip opens by itself for a new question, once. A question the student
 * already minimised stays minimised until the next one arrives.
 */
export function opensForQuestion(previousQuestionId: string | null, questionId: string | null): boolean {
  return questionId !== null && questionId !== previousQuestionId
}
