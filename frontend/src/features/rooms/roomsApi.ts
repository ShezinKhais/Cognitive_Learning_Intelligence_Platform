import { apiAuthenticatedGet, apiAuthenticatedRequest } from '../../api'

export interface RoomMember {
  user_id: string
  name: string
  connected: boolean
}

export interface RoomPlan {
  running: boolean
  rooms: { label: string; students: RoomMember[] }[]
  unassigned: RoomMember[]
}

const path = (sessionId: string) => `/sessions/${encodeURIComponent(sessionId)}/rooms`

export function getRoomPlan(sessionId: string): Promise<RoomPlan> {
  return apiAuthenticatedGet(path(sessionId))
}

export function sendRoomPlan(sessionId: string, body: { rooms: { label: string; user_ids: string[] }[] }): Promise<RoomPlan> {
  return apiAuthenticatedRequest(path(sessionId), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function closeRooms(sessionId: string): Promise<RoomPlan> {
  return apiAuthenticatedRequest(path(sessionId), { method: 'DELETE' })
}
