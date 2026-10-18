import { useEffect } from 'react'

/** Name the browser tab after the page, so a row of tabs can be told apart. */
export function useDocumentTitle(name: string | undefined) {
  useEffect(() => {
    if (name) document.title = `${name} · C.L.I.P`
  }, [name])
}
