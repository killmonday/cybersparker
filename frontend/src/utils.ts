/**
 * 复制文本到剪贴板。
 * 优先使用 Clipboard API（需安全上下文），失败时降级为 execCommand（兼容 HTTP）。
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // 非 HTTPS 环境（如内网 HTTP 部署）navigator.clipboard 不可用，降级到传统方案
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  try {
    document.execCommand('copy')
    return true
  } catch {
    return false
  } finally {
    document.body.removeChild(textarea)
  }
}
