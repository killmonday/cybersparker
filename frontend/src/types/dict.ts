export type DictItem = {
  id: number
  name: string
  path_count: number
  groups: string[]
  created_at: string
}

export type DictListResponse = {
  items: DictItem[]
  page: number
  rows_per_page: number
  total: number
  total_pages: number
  filters: { q: string }
}

export type DictGroupItem = {
  id: number
  name: string
  description: string
  creatime: string
}

export type DictGroupListResponse = {
  items: DictGroupItem[]
  page: number
  rows_per_page: number
  total: number
  total_pages: number
  filters: { q: string }
}
