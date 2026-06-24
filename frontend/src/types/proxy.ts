export type ProxyItem = {
  id: number
  proxy_type_label: string
  proxy_address: string
  proxy_port: number
  created_at: string
}

export type ProxyTypeChoice = {
  value: number
  label: string
}

export type ProxyListResponse = {
  items: ProxyItem[]
  page: number
  rows_per_page: number
  total: number
  total_pages: number
  filters: { q: string }
  proxy_type_choices: ProxyTypeChoice[]
}

export type ProxyFormState = {
  id?: number
  proxy_type: string
  proxy_address: string
  proxy_port: string
  remark: string
}

export type ProxyDetailResponse = {
  status: boolean
  data: {
    id: number
    proxy_type: number
    proxy_address: string
    proxy_port: number
    remark: string | null
  }
  proxy_type_choices: ProxyTypeChoice[]
}
