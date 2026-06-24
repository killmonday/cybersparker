import HistoryEngineResultPicker from '../components/HistoryEngineResultPicker'
import type { HistoryEngineResult } from '../components/HistoryEngineResultPicker'
import { HISTORY_ENGINE_FILES_FIELD, HISTORY_ENGINE_INPUT_TYPE } from './historyEngineResultContract'

type PickerProps = Parameters<typeof HistoryEngineResultPicker>[0]
type IsExact<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false
type Assert<T extends true> = T

type _HistoryEngineInputType = Assert<IsExact<typeof HISTORY_ENGINE_INPUT_TYPE, '5'>>
type _HistoryEngineFilesField = Assert<IsExact<typeof HISTORY_ENGINE_FILES_FIELD, 'history_engine_files[]'>>
type _PickerSelectedValue = Assert<IsExact<PickerProps['selected'], string[]>>
type _PickerSelectionCallback = Assert<IsExact<Parameters<PickerProps['onSelectionChange']>[0], string[]>>

const result: HistoryEngineResult = {
  target: 'EXP_input/engine_assets/demo.txt',
  engine_type: 'fofa',
  engine_query: 'title="demo"',
  task_name: 'demo-task',
  creat_time: '2026-06-07 12:00:00',
  target_count: 2,
}

const pickerProps: PickerProps = {
  results: [result],
  selected: [result.target],
  onSelectionChange(next) {
    const selectedFiles: string[] = next
    void selectedFiles
  },
  onRefresh() {},
}

const formData = new FormData()
if (HISTORY_ENGINE_INPUT_TYPE === '5') {
  pickerProps.selected.forEach(file => formData.append(HISTORY_ENGINE_FILES_FIELD, file))
}

void formData
