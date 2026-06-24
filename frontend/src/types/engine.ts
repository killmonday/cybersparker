import type { ChoiceOption } from './index'

export type EngineItem = {
  id: number
  engine_type: string
  api_base_url: string
  account_email: string
  use_proxy: boolean
  proxy_label: string
  remark: string
}

export type EngineDefaults = {
  api_base_url: string
  needs_email: boolean
}

export type EngineListResponse = {
  items: EngineItem[]
  page: number
  rows_per_page: number
  total: number
  total_pages: number
  filters: { q: string }
  engine_type_choices: ChoiceOption[]
  engine_defaults: Record<string, EngineDefaults>
  proxy_choices: ChoiceOption[]
}

export type EngineFormState = {
  id?: number
  engine_type: string
  api_base_url: string
  account_email: string
  api_key: string
  use_proxy: boolean
  proxy: string
  remark: string
}

export type EngineDetailResponse = {
  status: boolean
  data: {
    id: number
    engine_type: string
    api_base_url: string
    account_email: string | null
    api_key: string
    use_proxy: boolean
    proxy: number | null
    remark: string | null
  }
  engine_type_choices: ChoiceOption[]
  proxy_choices: ChoiceOption[]
}
