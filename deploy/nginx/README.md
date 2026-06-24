# 部署指南

> 最后更新：2026-06-03

## 部署架构

```
浏览器 → Nginx :28600
              ├─ /react-shell/*  → Nginx 直接返回 React 编译产物（含 index.html、JS、CSS）
              │                    Django 完全不参与 React 页面渲染
              │                    开发模式时转发到 Vite :5173（HMR 热更新）
              ├─ /static/*       → Nginx 直接返回 Django 静态文件
              ├─ /api/*          → Django :8999  （JSON API）
              ├─ /login /logout  → Django :8999  （认证）
              └─ 其他路径         → Django :8999  （旧页面，保留备用）
```

## 前置条件

- Debian 12+ / Ubuntu 20.04+
- Python 3.11、PostgreSQL、Redis、Celery（项目已配置）
- Node.js 18+（前端构建用）

## 第一步：安装 Nginx

```bash
sudo apt update
sudo apt install -y nginx

# 确认运行
sudo systemctl status nginx
```

## 第二步：配置 Nginx

配置文件是一个完整的 `server` 块，直接放入 sites-available：

```bash
# 复制配置
sudo cp deploy/nginx/react-shell.conf /etc/nginx/sites-available/react-shell

# 把 /workspaces/cybersparker 替换为项目实际路径（路径不同时执行）
sudo sed -i 's|/workspaces/cybersparker|/home/your-user/cybersparker|g' /etc/nginx/sites-available/react-shell

# 启用
sudo ln -sf /etc/nginx/sites-available/react-shell /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# 检查语法
sudo nginx -t

# 重载
sudo nginx -s reload
```

## 第三步：构建 React 前端

```bash
cd frontend
npm install
npm run build
# 输出到 ../app_cybersparker/static/react-shell/
```

## 第四步：启动服务

```bash
# Django + Celery（项目已有脚本）
./start.sh

# 确认端口
ss -tlnp | grep -E '28600|8999|6379'
# 28600   nginx
# 8999 python（Django）
```

## 开发模式

改完前端代码后不需要每次都 `npm run build`。切到开发模式让 Nginx 把 React 请求转发到 Vite 热更新服务器：

```bash
# 终端 1：启动 Vite 开发服务器
cd frontend
npm run dev
```

然后编辑 `/etc/nginx/sites-available/react-shell`，把这段注释切换：

```nginx
location /react-shell/ {
    # === 生产模式（注释掉下面两行）===
    # alias /path/to/cybersparker/app_cybersparker/static/react-shell/;
    # try_files $uri /react-shell/index.html;

    # === 开发模式（取消注释下面几行）===
    proxy_pass http://127.0.0.1:5173/react-shell/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```

并取消注释 Vite HMR 辅助路径：

```nginx
location ~ ^/(@vite|@react-refresh|src|node_modules)/ {
    proxy_pass http://127.0.0.1:5173;
    ...
}
```

```bash
sudo nginx -t && sudo nginx -s reload
```

访问 `http://服务器IP/react-shell/dashboard`，改代码即刷新，无需手动 build。

切回生产时把配置反向注释，重新 `npm run build` 即可。

## 路径说明

无论开发还是生产，浏览器都通过 Nginx 访问，URL 前缀统一为 `/react-shell/`。
不会有之前"开发模式下 basename 为空"的问题。

## Django 旧页面

所有旧 Django URL（`/expload/list`、`/Identify_task/*` 等）保持不变，Nginx 透传到 Django。
React 新页面通过 `/react-shell/*` 访问，两者共存互不干扰。
