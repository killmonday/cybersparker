import useSWR from 'swr'

const fetcher = (url: string) =>
  fetch(url, { credentials: 'same-origin' }).then((r) => r.json())

/**
 * 批量轮询任务状态。
 * 返回 { [taskId]: statusData } 的 map，直接替代手写 setInterval 轮询。
 *
 * @param batchUrl  批量状态接口地址，如 '/api/v1/identify-tasks/status-batch'
 * @param ids       需要轮询的任务 ID 列表，为空时不发请求
 * @param interval  轮询间隔 ms，默认 3000
 */
export function useTaskPolling<T = Record<string, unknown>>(
  batchUrl: string,
  ids: number[],
  interval = 3000,
): Record<number, T> {
  const key = ids.length > 0 ? `${batchUrl}?ids=${ids.join(',')}` : null

  const { data } = useSWR(key, fetcher, {
    refreshInterval: interval,
    dedupingInterval: 2000,
    revalidateOnFocus: false,
  })

  return (data?.data as Record<number, T>) ?? {}
}
