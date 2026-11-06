import { PolicyLayout, PolicySection } from './policy/PolicyLayout'
import { BACKUPS_KEPT, RETENTION_DAYS } from './policy/policyFacts'

export default function PrivacyPage() {
  return (
    <PolicyLayout
      title="Privacy notice"
      summary="What C.L.I.P collects when you use it in a class, what it never collects, who can see it, and how long it is kept."
      other={{ to: '/terms', label: 'terms of use' }}
    >
      <PolicySection title="What C.L.I.P collects">
        <ul>
          <li>Your account: your name, university email address, role and the course you are enrolled on.</li>
          <li>Your consent choices, and when you made them.</li>
          <li>Class activity: the sessions you joined, your answers to checkpoint questions, and any special consideration request you submit.</li>
          <li>Lecture material uploaded by lecturers, and the questions generated from it.</li>
          <li>
            If you turn on engagement monitoring: the camera and microphone readings described below, kept as one
            summary of numbers for each minute of a class.
          </li>
          <li>An audit record of actions taken while you are signed in: who did what, and when. It holds no content.</li>
        </ul>
      </PolicySection>

      <PolicySection title="Camera and microphone">
        <p>
          The camera and microphone indicators are optional. Each needs its own consent, and both need engagement
          monitoring to be on. When they are on, your browser works them out on your own device. C.L.I.P never sends
          video, pictures, sound or speech to its server.
        </p>
        <p>
          Giving consent does not turn a device on. You switch each indicator on yourself during a class, and your
          browser asks for permission first. You can decline, or turn either off, and still take part in everything.
        </p>
        <p>
          These indicators are separate from Microsoft Teams. If you turn on your camera or microphone in a Teams
          meeting, Teams handles that audio and video under Microsoft&apos;s own privacy terms, not C.L.I.P&apos;s.
        </p>
        <p>
          About every five seconds, your device sends C.L.I.P four values: the share of time you were facing the
          screen, whether a face was in view, whether you were speaking (yes or no), and how long that period was.
          The camera and microphone indicators send nothing else. C.L.I.P combines these values into one summary for
          each minute and keeps only that summary. You can turn either indicator off at any time from the class
          panel, and it stops at once.
        </p>
      </PolicySection>

      <PolicySection title="What C.L.I.P never collects">
        <ul>
          <li>Meeting audio, video, recordings or transcripts.</li>
          <li>Teams meeting chat messages.</li>
          <li>Pictures of your face, or any biometric template.</li>
          <li>Your conversations with the tutor. They are answered and then discarded; only the fact that a question was asked is logged.</li>
        </ul>
      </PolicySection>

      <PolicySection title="How it is used">
        <ul>
          <li>To run the class: sending checkpoint questions, recording answers and giving you feedback.</li>
          <li>To show your lecturer how the class is going: who is present, who answered, and the results.</li>
          <li>
            If you turned on engagement monitoring, to give your lecturer an estimate of engagement for each student
            (engaged, at risk, disengaged, or not enough data). Lecturers never see video, pictures or sound.
          </li>
          <li>To send you a private prompt if you seem to have drifted away. The camera alone is never enough for one.</li>
        </ul>
        <p>
          Engagement and comprehension estimates help your lecturer teach. They are not assessments and do not affect
          your marks, and leaving the optional indicators off is never counted against you.
        </p>
      </PolicySection>

      <PolicySection title="AI in C.L.I.P">
        <p>
          The AI models C.L.I.P uses run on its own server. Your answers, your questions and the lecture material are
          not sent to any outside AI provider.
        </p>
        <ul>
          <li>Questions are generated from your lecturer's material, and your lecturer reviews each one before it is used.</li>
          <li>The tutor gives hints and points to the slides it used. It can be wrong, so check what it says against the lecture material.</li>
          <li>Written answers are labelled automatically as a guide for your lecturer, who decides what they mean.</li>
        </ul>
      </PolicySection>

      <PolicySection title="Who can see your information">
        <ul>
          <li>You can see your own answers, summaries and progress.</li>
          <li>Your lecturer can see the classes they teach.</li>
          <li>Administrators manage accounts, data requests and the audit record.</li>
        </ul>
        <p>
          Every request is checked against your role on the C.L.I.P server. Other than through Microsoft Teams,
          described below, C.L.I.P does not send your information to anyone outside the system.
        </p>
        <p>
          When you use C.L.I.P inside a Teams meeting, Teams is run by Microsoft. Teams tells C.L.I.P when the meeting
          starts and ends, C.L.I.P asks Teams who is in the meeting, and Teams delivers C.L.I.P's messages: a card in
          the meeting chat naming the course and session when a checkpoint opens, and pop-ups. These messages only say
          that something is waiting in C.L.I.P; your answers and results are never in them.
        </p>
      </PolicySection>

      <PolicySection title="How long it is kept">
        <p>
          Information is held on the C.L.I.P server and travels over encrypted connections. By default, a
          session's records are deleted {RETENTION_DAYS} days after it ends: your answers, engagement and camera and
          microphone summaries, prompts and alerts. Your university can set a different period.
        </p>
        <p>
          Two things are kept after that:
        </p>
        <ul>
          <li>
            If your university turns on course history, a summary for each course and semester is kept before the
            session is deleted: how many sessions you attended, how many questions you tried and got right, and your
            average engagement and attention. It holds counts and averages only, never your answers, and only
            administrators can view it. It is kept until it is erased with your other information.
          </li>
          <li>
            The audit record, which says who did what and when but holds no content, is kept so actions on your
            information can be checked later. If your information is erased, your name and email are removed from
            your account, so the audit record no longer identifies you.
          </li>
        </ul>
        <p>
          Backups are kept for recovery. By default the last {BACKUPS_KEPT} daily backups are kept, so information
          that has been deleted leaves the backups within about a month.
        </p>
      </PolicySection>

      <PolicySection title="Your choices and requests">
        <ul>
          <li>You can turn the optional indicators on or off at any time. Declining one never blocks another.</li>
          <li>
            You can download a copy of the information C.L.I.P holds about you from <strong>My data</strong> in the
            student menu.
          </li>
          <li>
            You can ask for your information to be erased, also from <strong>My data</strong>. An administrator reviews
            the request before anything is deleted, and erasing cannot be undone.
          </li>
        </ul>
      </PolicySection>

      <PolicySection title="Questions">
        <p>
          Ask your lecturer, or the C.L.I.P administrator for your course. They can also make a request for a copy of
          your information or for its erasure on your behalf.
        </p>
      </PolicySection>
    </PolicyLayout>
  )
}
