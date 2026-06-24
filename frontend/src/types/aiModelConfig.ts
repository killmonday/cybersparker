export interface AiModelConfigItem {
  id: number
  name: string
  model_id: string
  api_url: string
  api_key: string
  model_type: 'thinking' | 'vision'
  model_type_label: string
  created_at: string
}

export interface AiModelConfigListResponse {
  status: boolean
  items: AiModelConfigItem[]
  model_type_choices: { value: string; label: string }[]
}

export interface AiModelConfigFormState {
  id?: number
  name: string
  model_id: string
  api_url: string
  api_key: string
  model_type: 'thinking' | 'vision'
}
