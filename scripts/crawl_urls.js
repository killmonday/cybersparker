#!/usr/bin/env node
/**
 * PoC 生成任务 — URL 爬取脚本
 *
 * 输入（stdin JSON）:
 *   {"urls": ["https://..."], "proxy": "http://host:port"|null, "timeout_ms": 30000, "save_dir": "/path/to/images"|null}
 *
 * 输出（stdout JSON）:
 *   {"results": [{"url": "...", "status": "success"|"failed", "markdown": "..."|null, "error": "..."|null, "elapsed_ms": 1234}]}
 *
 * 清洗管线:
 *   1. 内容提取（站点适配 + 通用噪音移除）
 *   2. turndown 转换（含自定义规则: table / kbd / details / 空元素）
 *   3. 图片保存：浏览器已加载的图片直接写磁盘，markdown 引用改为本地路径
 *   4. 后清洗（残留标签 / 实体解码 / 空白合并）
 */

const puppeteer = require('puppeteer');
const TurndownService = require('turndown');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

// ======================== 内网 IP 检测 ========================

const INTERNAL_RANGES = [
  /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/,
  /^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$/,
  /^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}$/,
  /^192\.168\.\d{1,3}\.\d{1,3}$/,
  /^169\.254\.\d{1,3}\.\d{1,3}$/,
  /^0\.0\.0\.0$/,
  /^0{1,3}\.0{1,3}\.0{1,3}\.0{1,3}$/,
];

function isInternalHost(hostname) {
  if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1') return true;
  for (const re of INTERNAL_RANGES) {
    if (re.test(hostname)) return true;
  }
  return false;
}

// ======================== URL 校验 ========================

function validateUrl(raw) {
  let url;
  try {
    url = new URL(raw);
  } catch {
    return { valid: false, error: `无效 URL: ${raw}` };
  }
  if (!['http:', 'https:'].includes(url.protocol)) {
    return { valid: false, error: `不支持的协议: ${url.protocol}` };
  }
  if (isInternalHost(url.hostname)) {
    return { valid: false, error: `拒绝访问内网地址: ${url.hostname}` };
  }
  return { valid: true, url: url.href };
}

// ======================== 内容提取（浏览器上下文） ========================

/**
 * 在页面上下文中执行，返回应转换的 HTML 字符串。
 * 站点适配规则按域名匹配，未匹配则走通用提取。
 *
 * 注意：此函数被序列化后在浏览器上下文中执行，不能引用外部 Node.js 变量。
 */
function contentExtractionScript(url) {
  // 内联 escapeHtml（浏览器上下文不可访问 Node.js 作用域）
  function escHtml(text) {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  var hostname = new URL(url).hostname;

  // ---- 通用噪音移除 ----
  var NOISE = [
    'script', 'style', 'noscript', 'iframe', 'svg', 'canvas', 'object', 'embed',
    'nav', 'footer', 'header',
    '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
    '.header', '.footer', '.sidebar', '.nav', '.navigation',
    '.cookie-banner', '.cookie-consent', '.cookie-notice',
    '.advertisement', '.ad', '.ads', '.adsbygoogle',
    '#comments', '.comments', '.comment-section', '.comment-list',
    '.social-share', '.share-buttons', '.article-share',
    '[aria-hidden="true"]',
    '[popover]', 'dialog',
    '.related-posts', '.recommended', '.recommendations',
    '.sidebar-nav', '.side-bar', '#sidebar',
    '.top-bar', '.topbar', '#topbar',
  ];
  NOISE.forEach(function (sel) {
    try {
      var els = document.querySelectorAll(sel);
      for (var i = 0; i < els.length; i++) { els[i].remove(); }
    } catch (_) { /* 选择器语法异常则跳过 */ }
  });

  // 移除 HTML 注释
  var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_COMMENT);
  var comments = [];
  while (walker.nextNode()) { comments.push(walker.currentNode); }
  comments.forEach(function (c) { c.remove(); });

  // ---- 站点适配 ----

  // GitHub
  if (hostname === 'github.com' || hostname === 'www.github.com') {
    // README / wiki / issue / PR 正文
    var readme = document.querySelector('article.markdown-body');
    if (readme) return readme.innerHTML;

    // 文件预览页 (blob): 提取代码行
    var codeLines = document.querySelectorAll('.blob-code-inner, .react-code-line-contents');
    if (codeLines.length > 0) {
      var parts = [];
      for (var i = 0; i < codeLines.length; i++) { parts.push(codeLines[i].textContent); }
      return '<pre><code>' + escHtml(parts.join('\n')) + '</code></pre>';
    }

    // 新版 GitHub 代码视图
    var codeArea = document.querySelector('[data-testid="code-content"]');
    if (codeArea) {
      return '<pre><code>' + escHtml(codeArea.textContent) + '</code></pre>';
    }

    // 通用正文区
    var main = document.querySelector('main');
    if (main) return main.innerHTML;
  }

  // 知乎
  if (hostname.endsWith('zhihu.com')) {
    var content = document.querySelector(
      '.RichContent-inner, .Post-RichText, ' +
      '.QuestionAnswer-content, .AnswerCard-content, ' +
      '.Article-content, article'
    );
    if (content) return content.innerHTML;
  }

  // 微信公众号
  if (hostname === 'mp.weixin.qq.com') {
    var wxContent = document.querySelector('#js_content, .rich_media_content');
    if (wxContent) return wxContent.innerHTML;
  }

  // ---- 通用正文查找 ----
  var CANDIDATES = [
    'article',
    'main',
    '[role="main"]',
    '.markdown-body',
    '.post-content', '.article-content', '.entry-content',
    '.post-body', '.article-body',
    '.content', '#content',
    '.page-content', '#page-content',
    '.container', '.wrapper',
  ];
  for (var i = 0; i < CANDIDATES.length; i++) {
    var el = document.querySelector(CANDIDATES[i]);
    if (el && el.textContent.trim().length > 200) {
      return el.innerHTML;
    }
  }

  return document.body.innerHTML;
}

// ======================== turndown 自定义规则 ========================

function addCustomRules(turndownService) {
  // ---- <table> → markdown table ----
  turndownService.addRule('tableCell', {
    filter: ['th', 'td'],
    replacement: function (content) {
      return cell(content, this);  // eslint-disable-line
    },
  });

  turndownService.addRule('tableRow', {
    filter: 'tr',
    replacement: function (content) {
      var borderCells = '';
      var alignMap = { left: ':--', right: '--:', center: ':-:' };

      if (isHeadingRow(this)) {  // eslint-disable-line
        var row = this.parentElement;  // eslint-disable-line
        for (var i = 0; i < row.children.length; i++) {
          var child = row.children[i];
          var align = (child.getAttribute('align') || '').toLowerCase();
          var border = alignMap[align] || '---';
          borderCells += cell(border, this);  // eslint-disable-line
        }
      }
      return '\n' + content + (borderCells ? '\n' + borderCells : '');
    },
  });

  turndownService.addRule('table', {
    filter: 'table',
    replacement: function (content) {
      // 紧凑表格：首尾空行各一
      var lines = content.trim().split('\n');
      // 跳过纯空的首行
      if (lines.length > 0 && lines[0] === '') lines.shift();
      // 每行: | cell | cell |
      var result = [];
      for (var i = 0; i < lines.length; i++) {
        var line = lines[i].trim();
        if (!line) continue;
        result.push('| ' + line + ' |');
      }
      return '\n\n' + result.join('\n') + '\n\n';
    },
  });

  // ---- <kbd> → `K` ----
  turndownService.addRule('kbd', {
    filter: 'kbd',
    replacement: function (content) {
      return '`' + content + '`';
    },
  });

  // ---- <details>/<summary> —— HTML 穿透（常见于 GitHub） ----
  turndownService.addRule('details', {
    filter: function (node) {
      return node.nodeName === 'DETAILS';
    },
    replacement: function (content) {
      return '\n<details>\n' + content.trim() + '\n</details>\n';
    },
  });

  // ---- <sup> / <sub> ----
  turndownService.addRule('sup', {
    filter: 'sup',
    replacement: function (content) { return '^' + content + '^'; },
  });
  turndownService.addRule('sub', {
    filter: 'sub',
    replacement: function (content) { return '~' + content + '~'; },
  });

  // ---- 空链接移除（保留包含图片的链接） ----
  turndownService.addRule('emptyLink', {
    filter: function (node, options) {
      return node.nodeName === 'A'
        && (!node.textContent || !node.textContent.trim())
        && node.querySelectorAll('img').length === 0;
    },
    replacement: function () { return ''; },
  });

  // ---- 空元素移除 ----
  function isEmpty(node) {
    return node.nodeType === 1 &&
      !node.textContent.trim() &&
      node.querySelectorAll('img,video,iframe,canvas,svg').length === 0;
  }
  turndownService.addRule('emptyBlock', {
    filter: function (node) {
      return node.nodeType === 1 &&
        ['DIV', 'SECTION', 'SPAN', 'P'].includes(node.nodeName) &&
        isEmpty(node);
    },
    replacement: function () { return ''; },
  });
}

// ---- table 辅助函数 ----
function cell(content, node) {
  if (!node || !node.parentNode) return ' ' + content + ' ';
  var index = Array.prototype.indexOf.call(node.parentNode.childNodes, node);
  var prefix = ' ';
  var suffix = ' ';
  if (index === 0) prefix = ' ';
  return prefix + content + suffix;
}

function isHeadingRow(node) {
  if (!node || !node.parentNode) return false;
  var parent = node.parentNode.tagName || '';
  if (parent === 'THEAD' || parent === 'TFOOT') return true;
  if (parent !== 'TABLE') return false;
  // 第一行且全为 th → 视为表头
  var firstRow = node.parentNode.querySelector('tr');
  if (firstRow !== node) return false;
  var cells = node.children;
  for (var i = 0; i < cells.length; i++) {
    if (cells[i].tagName !== 'TH') return false;
  }
  return true;
}

// ======================== Markdown 后清洗 ========================

function cleanMarkdown(md) {
  return md
    // 移除残留的 HTML 标签（保留 <details> <summary>）
    .replace(/<(?!\/?(?:details|summary)[\s>])[^>]*>/gi, '')
    // 解码常用 HTML 实体
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/&#160;/g, ' ')
    // 解码数字实体
    .replace(/&#(\d+);/g, function (_, n) { return String.fromCharCode(parseInt(n, 10)); })
    // 合并 3 个以上连续空行为 2 个
    .replace(/\n{3,}/g, '\n\n')
    // 去掉只含空白字符的行
    .replace(/\n[ \t]+\n/g, '\n\n')
    // 去掉行首尾多余空格
    .split('\n').map(function (l) { return l.trimEnd(); }).join('\n')
    // 去掉开头/结尾空行
    .trim();
}

// ======================== 图片保存 ========================

/**
 * 从 markdown 中提取图片引用，匹配浏览器已加载的图片 buffer，写磁盘，
 * 返回更新了本地路径的 markdown。
 */
function saveImagesToDisk(markdown, pageUrl, imageBuffers, saveDir) {
  if (!saveDir || Object.keys(imageBuffers).length === 0) return markdown;

  var imgRegex = /!\[([^\]]*)\]\(([^)]*)\)/g;
  var replacements = {};

  var match;
  while ((match = imgRegex.exec(markdown)) !== null) {
    var fullMatch = match[0];
    var altText = match[1];
    var imgUrl = match[2];

    // 解析图片 URL：相对路径 → 绝对 URL
    var resolvedUrl = imgUrl;
    try {
      if (imgUrl.startsWith('/')) {
        resolvedUrl = new URL(imgUrl, pageUrl).href;
      } else if (imgUrl.startsWith('http')) {
        resolvedUrl = imgUrl;
      } else {
        resolvedUrl = new URL(imgUrl, pageUrl).href;
      }
    } catch (_) {
      continue;
    }

    // 在已加载的图片中查找匹配
    var buffer = imageBuffers[resolvedUrl];
    if (!buffer) {
      // 尝试 URL 路径后缀模糊匹配
      var needle = '';
      try { needle = new URL(resolvedUrl).pathname.split('/').pop(); } catch (_) {}
      if (needle) {
        for (var key in imageBuffers) {
          if (key.endsWith(needle)) { buffer = imageBuffers[key]; break; }
        }
      }
    }

    if (buffer && buffer.length > 0) {
      var hash = crypto.createHash('md5').update(buffer).digest('hex').substring(0, 12);
      // 根据文件头判断类型
      var ext = '.png';
      if (buffer[0] === 0xFF && buffer[1] === 0xD8) ext = '.jpg';
      else if (buffer[0] === 0x47 && buffer[1] === 0x49) ext = '.gif';
      else if (buffer[0] === 0x52 && buffer[1] === 0x49) ext = '.webp';
      else if (buffer[1] === 0x50 && buffer[2] === 0x4E) ext = '.png';

      var filename = hash + ext;
      try {
        fs.mkdirSync(saveDir, { recursive: true });
        fs.writeFileSync(path.join(saveDir, filename), buffer);
        replacements[fullMatch] = '![' + altText + '](img/' + filename + ')';
      } catch (_) { /* 写磁盘失败则保留原 URL */ }
    }
  }

  // 按匹配文本长度降序替换
  var sortedKeys = Object.keys(replacements).sort(function(a, b) { return b.length - a.length; });
  for (var i = 0; i < sortedKeys.length; i++) {
    markdown = markdown.split(sortedKeys[i]).join(replacements[sortedKeys[i]]);
  }

  return markdown;
}

// ---- 渐进滚动触发懒加载 ----
async function progressiveScroll(page) {
  var viewportHeight = await page.evaluate(function () { return window.innerHeight; });
  var totalHeight = await page.evaluate(function () { return document.body.scrollHeight; });
  if (totalHeight <= viewportHeight * 1.5) return; // 短页面无需渐进滚
  var steps = Math.ceil(totalHeight / viewportHeight);
  for (var i = 1; i <= steps; i++) {
    await page.evaluate(function (y) { window.scrollTo(0, y); }, i * viewportHeight * 0.7);
    await new Promise(function (r) { setTimeout(r, 300); });
  }
  await page.evaluate(function () { window.scrollTo(0, 0); });
  await new Promise(function (r) { setTimeout(r, 200); });
}

// ---- currentSrc 修正：应对 src 属性与实际加载 URL 不一致 ----
async function fixSrcWithCurrentSrc(page) {
  await page.evaluate(function () {
    document.querySelectorAll('img').forEach(function (img) {
      var computedSrc = img.currentSrc || '';
      var domSrc = img.getAttribute('src') || '';
      if (computedSrc && computedSrc !== domSrc) {
        img.setAttribute('src', computedSrc);
      }
    });
  });
}

// ======================== 单个 URL 爬取 ========================

function buildTurndownService() {
  var svc = new TurndownService({
    headingStyle: 'atx',
    codeBlockStyle: 'fenced',
    bulletListMarker: '-',
    emDelimiter: '*',
  });
  addCustomRules(svc);
  return svc;
}

async function crawlUrl(browser, url, timeoutMs, turndownService, saveDir) {
  var start = Date.now();
  var page = await browser.newPage();

  // 拦截浏览器已加载的图片响应，收集 buffer
  var imageBuffers = {};
  page.on('response', async function (response) {
    var ct = (response.headers()['content-type'] || '').toLowerCase();
    if (ct.startsWith('image/') && response.status() === 200) {
      try {
        imageBuffers[response.url()] = await response.buffer();
      } catch (_) {}
    }
  });

  try {
    // ---- 反检测：在页面 JS 执行前注入 ----
    await page.evaluateOnNewDocument(function () {
      // 删除 webdriver 标记（原型级删除，防 'in' 检查）
      Object.defineProperty(navigator, 'webdriver', { get: function () { return undefined; } });
      try { delete Object.getPrototypeOf(navigator).webdriver; } catch (_) {}

      // 模拟 chrome.runtime（headless Chrome 缺失此项）
      window.chrome = {
        runtime: {},
        loadTimes: function () {},
        csi: function () {},
        app: {},
      };

      // plugins（至少需要 Chrome PDF Viewer）
      Object.defineProperty(navigator, 'plugins', {
        get: function () {
          var p = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format', length: 1 },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '', length: 1 },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '', length: 2 },
          ];
          p.item = function (i) { return p[i]; };
          p.namedItem = function (n) { for (var k = 0; k < p.length; k++) { if (p[k].name === n) return p[k]; } return null; };
          p.refresh = function () {};
          return p;
        },
      });

      // languages
      Object.defineProperty(navigator, 'languages', {
        get: function () { return ['zh-CN', 'zh', 'en-US', 'en']; },
      });

      // platform（与 UA 中 Win64 一致）
      Object.defineProperty(navigator, 'platform', {
        get: function () { return 'Win32'; },
      });

      // hardwareConcurrency / deviceMemory
      Object.defineProperty(navigator, 'hardwareConcurrency', { get: function () { return 8; } });
      Object.defineProperty(navigator, 'deviceMemory', { get: function () { return 8; } });

      // permissions 查询
      var _origQuery = window.navigator.permissions.query;
      window.navigator.permissions.query = function (parameters) {
        if (parameters.name === 'notifications') {
          return Promise.resolve({ state: Notification.permission });
        }
        return _origQuery.call(window.navigator.permissions, parameters);
      };

      // WebGL 供应商/渲染器伪装
      var _getParameter = WebGLRenderingContext.prototype.getParameter;
      WebGLRenderingContext.prototype.getParameter = function (parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return _getParameter.call(this, parameter);
      };
    });

    // ---- viewport 与 UA 一致 ----
    await page.setViewport({ width: 1920, height: 1080 });
    await page.setUserAgent(
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    );

    // ---- 额外请求头 ----
    await page.setExtraHTTPHeaders({
      'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    });

    // 1. 等页面完全加载，再等正文区出现
    await page.goto(url, { waitUntil: 'networkidle2', timeout: timeoutMs });
    try { await page.waitForSelector('article, main, .markdown-body, [role="main"]', { timeout: 10000 }); } catch (_) {}

    // 1.5 微信公众号"阅读全文"展开
    try {
      var readMoreBtn = await page.$('#read_more, .read_more, .article-more, a[data-type="readmore"]');
      if (readMoreBtn) {
        await readMoreBtn.click();
        await new Promise(function (r) { setTimeout(r, 2000); });
      }
    } catch (_) {}

    // 2. 渐进滚动触发懒加载图片（必须在提取 HTML 之前）
    await progressiveScroll(page);
    await new Promise(function (r) { setTimeout(r, 500); });

    // 3. 等待图片加载完成（排除 data: URI 和空 src）
    try {
      await page.waitForFunction(function () {
        var imgs = document.querySelectorAll('img');
        if (imgs.length === 0) return true;
        return Array.from(imgs).every(function (img) {
          if (!img.src || img.src.startsWith('data:')) return true;
          return img.complete;
        });
      }, { timeout: 15000 });
    } catch (_) {}

    // 4. 用 currentSrc 修正 src 属性（处理 HTTP→HTTPS 重定向、srcset 解析差异）
    await fixSrcWithCurrentSrc(page);

    // 5. 提取内容
    var html = await page.evaluate(contentExtractionScript, url);

    // 6. turndown 转换 → 后清洗
    var rawMd = turndownService.turndown(html);
    var markdown = cleanMarkdown(rawMd);

    // 7. 图片保存：buffer 写磁盘，markdown 引用改为本地路径
    markdown = saveImagesToDisk(markdown, url, imageBuffers, saveDir);

    var elapsed = Date.now() - start;
    await page.close();
    return { url: url, status: 'success', markdown: markdown, error: null, elapsed_ms: elapsed };
  } catch (err) {
    var elapsed = Date.now() - start;
    try { await page.close(); } catch (_) {}
    return { url: url, status: 'failed', markdown: null, error: err.message || String(err), elapsed_ms: elapsed };
  }
}

// ======================== 主流程 ========================

async function main() {
  var input = '';
  process.stdin.setEncoding('utf8');
  var readable = process.stdin;
  for await (var chunk of readable) {
    input += chunk;
  }

  var config;
  try {
    config = JSON.parse(input);
  } catch (_) {
    process.stdout.write(JSON.stringify({ results: [], error: 'Invalid JSON input' }));
    process.exit(1);
  }

  var urls = config.urls || [];
  var timeoutMs = config.timeout_ms || 30000;
  var saveDir = config.save_dir || null;

  // URL 校验
  var validated = urls.map(validateUrl);

  // 启动浏览器
  var launchArgs = [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--disable-blink-features=AutomationControlled',
    '--disable-features=IsolateOrigins,site-per-process',
    '--disable-gpu',
  ];
  if (config.proxy) {
    launchArgs.push('--proxy-server=' + config.proxy);
  }

  // 优先用环境变量 PUPPETEER_EXECUTABLE_PATH，其次自动检测已安装的 Chrome/Chromium
  var executablePath = process.env.PUPPETEER_EXECUTABLE_PATH || null;
  if (!executablePath) {
    var candidates = [];
    try {
      var cacheDir = require('path').join(require('os').homedir(), '.cache', 'puppeteer');
      var dirs = require('fs').readdirSync(cacheDir);
      for (var i = 0; i < dirs.length; i++) {
        var chromePath = require('path').join(cacheDir, dirs[i], 'chrome-linux64', 'chrome');
        if (require('fs').existsSync(chromePath)) { candidates.push(chromePath); }
      }
    } catch (_) {}
    if (candidates.length === 0) {
      candidates = ['/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome'];
    }
    for (var j = 0; j < candidates.length; j++) {
      if (require('fs').existsSync(candidates[j])) { executablePath = candidates[j]; break; }
    }
  }

  var browser;
  try {
    var launchOpts = {
      headless: 'new',
      args: launchArgs,
      ignoreDefaultArgs: ['--enable-automation'],
    };
    if (executablePath) launchOpts.executablePath = executablePath;
    browser = await puppeteer.launch(launchOpts);
  } catch (err) {
    var results = validated.map(function (v) {
      if (!v.valid) {
        return { url: v.url || '', status: 'failed', markdown: null, error: v.error, elapsed_ms: 0 };
      }
      return { url: v.url, status: 'failed', markdown: null, error: '浏览器启动失败: ' + err.message, elapsed_ms: 0 };
    });
    process.stdout.write(JSON.stringify({ results: results }));
    process.exit(0);
  }

  var turndownService = buildTurndownService();

  var results = [];
  for (var i = 0; i < validated.length; i++) {
    var v = validated[i];
    if (!v.valid) {
      results.push({ url: v.url || '', status: 'failed', markdown: null, error: v.error, elapsed_ms: 0 });
      continue;
    }
    var result = await crawlUrl(browser, v.url, timeoutMs, turndownService, saveDir);
    results.push(result);
  }

  await browser.close();
  process.stdout.write(JSON.stringify({ results: results }));
}

main().catch(function (err) {
  process.stdout.write(JSON.stringify({ results: [], error: String(err) }));
  process.exit(1);
});
