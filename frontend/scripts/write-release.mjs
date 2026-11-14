import { writeFile } from 'node:fs/promises'

const revision = process.env.CLIP_RELEASE_SHA ?? 'unknown'
if (!/^(unknown|[a-f0-9]{40})$/.test(revision)) throw new Error('Set a full git revision or unknown.')
const switches = [
  'VITE_MATERIAL_PIPELINE_ENABLED', 'VITE_LIVE_SESSIONS_ENABLED',
  'VITE_SOCRATIC_CHAT_ENABLED', 'VITE_LOCAL_ATTENTION_ENABLED', 'VITE_TEAMS_MOCK_ENABLED',
]
const flags = Object.fromEntries(switches.map(name => [name, process.env[name] === 'true']))
await writeFile('dist/release.json', JSON.stringify({ release_sha: revision, flags }) + '\n')
