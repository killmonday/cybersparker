export type PluginItem = {
  id: number
  title: string
  CVE: string
  severity: string
  severity_label: string
  plugin_language_label: string
  use_label: string
  type_label: string
  tags: string[]
  detail_url: string
}

export type PluginListResponse = {
  items: PluginItem[]
  page: number
  rows_per_page: number
  total: number
  total_pages: number
  filters: {
    q: string
    severity: string
    tag: string
  }
  severity_choices: Array<{ value: string; label: string }>
}

export type PluginOption = { CVE: string; title: string }
