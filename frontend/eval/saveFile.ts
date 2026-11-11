// Hands the recorder pages' CSV to the browser as a download.
//
// The link is put in the page and the file's URL kept for a minute: Firefox
// ignores a click on a link that is not in the page, and Safari and Firefox
// can cancel a download whose URL is revoked straight after the click.
export function saveFile(name: string, text: string, type = 'text/csv'): void {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.style.display = 'none'
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
