export interface ZoneItem {
  id: number
  code: string
  name: string
  description: string
  is_system: boolean
  created_at: string
  asset_count: number
  auto_scan_task_count: number
  batch_task_count: number
  dirscan_task_count: number
  directory_result_count: number
}

export interface ZoneListResponse {
  zones: ZoneItem[]
}
