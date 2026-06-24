export type SessionPayload = {
  authenticated?: boolean
  user?: { id?: string }
  code?: string
  message?: string
  login_url?: string
}

export type ChoiceOption = {
  value: string | number
  label: string
}

/** Generic paginated list response */
export type PageResponse<T> = {
  items: T[]
  page: number
  rows_per_page: number
  total: number
  total_pages: number
}
