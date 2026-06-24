export type FingerprintItem = {
  id: number
  product: string
  condition: string
  created_at: string
  exp_count: number
}

export type FingerprintListResponse = {
  items: FingerprintItem[]
  page: number
  rows_per_page: number
  total: number
  total_pages: number
  filters: { q: string }
}

export type FingerprintFormState = {
  id?: number
  product: string
  condition: string
}

export type FingerprintDetailResponse = {
  status: boolean
  data: {
    id: number
    product: string
    condition: string
  }
}

export type FingerprintPluginItem = {
  id: number
  title: string
  CVE: string
  type_label: string
  severity_label: string
}

export type FingerprintPluginsResponse = {
  status: boolean
  items: FingerprintPluginItem[]
  page: number
  rows_per_page: number
  total: number
  total_pages: number
  filters: { q: string }
}
