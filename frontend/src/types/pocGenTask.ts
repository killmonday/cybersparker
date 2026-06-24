export interface PocGenTaskItem {
  id: number
  title: string
  task_type: 'url_crawl' | 'file_upload' | 'text_input'
  task_type_label: string
  plugin_language: 1 | 2 | null
  plugin_language_label: string
  thinking_model_id: number
  thinking_model_name: string
  vision_model_id: number | null
  vision_model_name: string | null
  proxy_id: number | null
  api_proxy_id: number | null
  urls: string
  uploaded_file: string
  crawl_status: 'pending' | 'processing' | 'success' | 'failed'
  crawl_status_label: string
  crawl_detail: string
  task_description_prompt: string
  plugin_spec_prompt: string
  reference_material_prompt: string
  custom_prompt: string
  generated_poc_content: string
  generated_metadata: string
  generated_extra_info: string
  saved_to_exp: boolean
  saved_exp_id: number | null
  status: 'pending' | 'crawling' | 'ready' | 'generating' | 'generated' | 'failed'
  status_label: string
  celery_task_id: string
  created_at: string
  updated_at: string
}

export interface PocGenTaskListResponse {
  status: boolean
  items: PocGenTaskItem[]
  total: number
  page: number
  total_pages: number
  rows_per_page: number
}

export interface AiModelOption {
  id: number
  name: string
  model_type: 'thinking' | 'vision'
}
