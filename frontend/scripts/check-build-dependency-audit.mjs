import { readFileSync } from 'node:fs'

const [, , reportPath, auditStatus] = process.argv
if (auditStatus === '0') process.exit(0)
if (auditStatus !== '1') throw new Error(`npm audit failed (exit ${auditStatus}).`)

const report = JSON.parse(readFileSync(reportPath, 'utf8'))
if (report.auditReportVersion !== 2 || report.error || !report.vulnerabilities) {
  throw new Error('npm audit did not return a usable vulnerability report.')
}

const blocking = new Set(['moderate', 'high', 'critical'])
const picomatchAdvisory = 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf'
const lock = JSON.parse(readFileSync('package-lock.json', 'utf8'))
const findings = []

for (const vulnerability of Object.values(report.vulnerabilities)) {
  for (const cause of vulnerability.via) {
    // npm reports dependents as references to the underlying findings.
    if (typeof cause === 'string') {
      if (!Object.hasOwn(report.vulnerabilities, cause)) {
        throw new Error(`npm audit returned an unresolved finding for ${cause}.`)
      }
      continue
    }
    if (!blocking.has(cause.severity)) continue

    const approvedBuildFinding =
      vulnerability.name === 'picomatch' &&
      cause.name === 'picomatch' &&
      cause.url === picomatchAdvisory &&
      vulnerability.nodes.length > 0 &&
      vulnerability.nodes.every(node =>
        lock.packages[node]?.dev === true && lock.packages[node].version === '4.0.5',
      )
    findings.push({ cause, approvedBuildFinding })
  }
}

if (!findings.length || findings.some(finding => !finding.approvedBuildFinding)) {
  for (const { cause, approvedBuildFinding } of findings) {
    if (!approvedBuildFinding) console.error(`${cause.name}: ${cause.url}`)
  }
  throw new Error('The build dependency audit has an unapproved failure. See npm-audit.json.')
}

console.warn('::warning::Known build-only picomatch advisory GHSA-fc5q-39xc-vjpf on locked 4.0.5. The separate production audit remains blocking.')
