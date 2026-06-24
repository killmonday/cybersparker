export type AutoExpResultItem = {
  id: number
  task_id: number
  target: string
  product: string
  plugin_name: string
  result: string
  creatime: string
}

export type AutoExpResultListResponse = {
  items: AutoExpResultItem[]
  page: number
  rows_per_page: number
  total: number
  total_pages: number
  filters: {
    id: string
    target: string
    product: string
    plugin: string
    result: string
    creatime: string
  }
}

export type ExpResultItem = {
  id: number
  task_type: number
  task_id: number
  plugin_name: string
  target: string
  result: string
  result_full: string
  creatime: string
}

export type ExpResultListResponse = {
  items: ExpResultItem[]
  page: number
  rows_per_page: number
  total: number
  total_pages: number
  filters: { q: string; id: string; target: string; plugin: string; result: string; creatime: string }
}

export type TaskResultItem = {
  id: number
  ip: string
  host: string
  protocol: string
  port: number
  title: string
  status_code: number | null
  country: string
  country_code: string
  target: string
  product: string[]
  creatime: string
  header: string
  favicon_md5: string
  favicon: string
  cert_org: string
  cert_org_unit: string
  cert_common_name: string
  cert_serial: string
  province: string
  city: string
  isp: string
  uri_path: string
  zone_id?: number | null
  zone_name?: string
  related_vulns: Array<{
    id: number
    exp_id: number | null
    plugin_name: string
    cve: string
    product: string
    target: string
  }>
}

export type FacetItem = {
  name: string
  count: number
  favicon?: string
}

export type TaskFacetResponse = {
  status: string | boolean
  field: string
  items: FacetItem[]
  has_more: boolean
  next_offset: number
  count_label: string
}

export type FaviconItem = {
  name: string
  count: number
  favicon?: string
}

export type TaskResultsResponse = {
  status: string | boolean
  results: TaskResultItem[]
  has_next: boolean
  has_prev: boolean
  next_cursor: string
  prev_cursor: string
  page_size: number
  estimated_total: number
  exact_total: number | null
  task_name: string
  favicon_items: FaviconItem[]
  favicon_has_more: boolean
  favicon_next_offset: number
  favicon_total: string
  favicon_deferred: boolean
  contract: {
    scope: string
    search_param: string
    pagination_params: string[]
    facet_params: string[]
    result_fields: string[]
    facet_endpoint: string
  }
  query: {
    scope: string
    search_param: string
    search_data: string
    task_id?: number
  }
}

export type PortOverviewRow = {
  protocol: string
  port: number
  target: string
  products: string[]
  is_current: boolean
}

export type PortOverviewResponse = {
  status: string
  rows: PortOverviewRow[]
  total: number
  has_more: boolean
}

export type IpDetailAssetItem = {
  id: number
  protocol: string
  port: number
  host: string
  target: string
  products: string[]
  title: string
  status_code: number | null
  cert_common_name: string
  cert_org: string
  related_vulns: Array<{
    id: number
    exp_id: number | null
    plugin_name: string
    cve: string
    product: string
  }>
  dirscan_results: Array<{
    uri_path: string
    status_code: number | null
    title: string
    products: string[]
  }>
}

export type IpDetailResponse = {
  status: string
  ip: string
  assets: IpDetailAssetItem[]
}

export type VulnResultDetail = {
  status: string
  result: string
  plugin_name: string
  cve: string
}

export type DashboardData = {
  cards: Array<{ name: string; count: number }>
  top_exp: Record<string, number>
  exp_types: Array<{ type_str: string; count: number }>
}
