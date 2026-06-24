export type TaskItem = {
  id: number
  task_name: string
  status: number
  status_key: string
  status_label: string
  status_class: string
  process: string
  phase: number
  phase_label: string
  pause_requested: boolean
  queued: boolean
  startTime: string | null
  endTime: string | null
  remark: string | null
  input_type: number
  vulnerability_scanning: number
  result_url: string
  react_result_url: string
  zone_id: number | null
  zone_name: string
}

export type TaskListResponse = {
  items: TaskItem[]
  page: number
  rows_per_page: number
  total: number
  total_pages: number
  filters: { q: string }
}

export type TaskPollData = {
  process: string
  status: string
  phase: number
  pause_requested: boolean
  queued: boolean
}

export type BatchTaskItem = {
  id: number
  task_name: string
  status: number
  status_key: string
  status_label: string
  status_class: string
  process: string
  pause_requested: boolean
  queued: boolean
  input_type: number
  startTime: string | null
  endTime: string | null
  remark: string | null
  run_mode: number
  exp_select_mode: number
  result_url: string
  react_result_url: string
  zone_id: number | null
  zone_name: string
}

export type BatchTaskListResponse = {
  items: BatchTaskItem[]
  page: number
  rows_per_page: number
  total: number
  total_pages: number
  filters: { q: string }
}

export type BatchTaskPollData = {
  process: string
  status: string
  pause_requested: boolean
  queued: boolean
}

export type ExportTaskItem = {
  id: number
  task_type: string
  task_type_label: string
  task_name: string
  status: string
  status_label: string
  total_rows: number | null
  creatime: string
  download_url: string
}

export type ExportTaskListResponse = {
  items: ExportTaskItem[]
  page: number
  rows_per_page: number
  total: number
  total_pages: number
}
