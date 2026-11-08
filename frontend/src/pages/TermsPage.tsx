import { PolicyLayout, PolicySection } from './policy/PolicyLayout'

export default function TermsPage() {
  return (
    <PolicyLayout
      title="Terms of use"
      summary="What C.L.I.P is for, how it should be used, and what it can and cannot be relied on for."
      other={{ to: '/privacy', label: 'privacy notice' }}
    >
      <PolicySection title="What C.L.I.P is">
        <p>
          C.L.I.P supports live online classes in Microsoft Teams. It sends short checkpoint questions during a
          lecture, gives students feedback and a tutor that offers hints, and shows lecturers how the class is going.
        </p>
        <p>
          It is a student capstone project and is still in development. Features may change, and it may sometimes be
          unavailable.
        </p>
      </PolicySection>

      <PolicySection title="Who may use it">
        <ul>
          <li>Students, lecturers and administrators with a C.L.I.P account for their course.</li>
          <li>Keep your password to yourself, and do not use anyone else's account.</li>
        </ul>
      </PolicySection>

      <PolicySection title="Intended use">
        <p>C.L.I.P is for learning and teaching, and its estimates are aids, not judgements.</p>
        <ul>
          <li>Engagement estimates and comprehension labels help a lecturer teach. They are not assessments, and are not to be used for grading or discipline.</li>
          <li>The optional camera and microphone indicators are the student's choice. Declining them is never held against anyone.</li>
        </ul>
      </PolicySection>

      <PolicySection title="People make the decisions">
        <ul>
          <li>Lecturers review every generated question before it reaches students.</li>
          <li>Alerts and estimates are suggestions. The lecturer decides what, if anything, to do about them.</li>
          <li>AI output can be wrong. Students should check the tutor's hints against the lecture material, and lecturers remain responsible for what they teach.</li>
        </ul>
      </PolicySection>

      <PolicySection title="Acceptable use">
        <ul>
          <li>Do not try to reach information or features your role does not allow, or to get around the platform's security.</li>
          <li>Do not try to disrupt a class or the service.</li>
          <li>Lecturers should upload only material they are allowed to share with their class.</li>
        </ul>
      </PolicySection>

      <PolicySection title="Your information">
        <p>
          How C.L.I.P handles information, including what it never collects and how long it keeps it, is set out in the
          privacy notice.
        </p>
      </PolicySection>

      <PolicySection title="Changes">
        <p>
          These terms may be updated as the project develops. The date at the top shows when they last changed.
        </p>
      </PolicySection>

      <PolicySection title="Questions">
        <p>Ask your lecturer, or the C.L.I.P administrator for your course.</p>
      </PolicySection>
    </PolicyLayout>
  )
}
