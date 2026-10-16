/** Match the existing room.confirm contract; never invent a Teams assignment. */
export function roomSelection(value: string): { room_label: string } | null {
  if (Array.from(value).some(character => {
    const code = character.codePointAt(0)!
    return code < 32 || (code >= 127 && code <= 159)
  })) return null
  const label = value.trim().replace(/\s+/gu, ' ')
  if (!label || Array.from(label).length > 100) return null
  return { room_label: label }
}
