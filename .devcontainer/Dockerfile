# FROM golang:1.20.14-bookworm
FROM golang:1.23-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV GO111MODULE=on
ENV GOPATH=/go
ENV PATH=$GOPATH/bin:/usr/local/go/bin:$PATH

# ===== APT 使用清华大学镜像 =====
COPY sources.list /etc/apt/sources.list

# ===== 防止证书问题下载node安装脚本不成功，可使用本地的 =====
COPY node_setup_22.x.sh /tmp/node_setup_22.x.sh

# ===== 安装系统依赖 =====
RUN apt-get update && apt-get install -y \
    curl \
    git \
    unzip \
    ca-certificates \
    build-essential \
    python3.11 \
    python3.11-dev \
    python3-pip \
    python3.11-venv \
    gnupg \
    lsb-release \
    vim \
    net-tools \
    iproute2 \
    p7zip-full 
    # && rm -rf /var/lib/apt/lists/*

# ===== Node.js 22（NodeSource）=====
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs 
    # && rm -rf /var/lib/apt/lists/*

RUN command -v npm >/dev/null || { \
    chmod +x /tmp/node_setup_22.x.sh; \
    /tmp/node_setup_22.x.sh; \
    apt-get install -y nodejs; \
}

# ===== NPM 镜像 =====
RUN npm config set registry https://registry.npmmirror.com


RUN npm install -g @musistudio/claude-code-router

# Python 默认版本
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# ===== 创建 venv（root 创建）=====
RUN python3 -m venv /opt/venv

# ✅ 让 vscode 用户默认使用这个 venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH=/opt/venv/bin:$PATH

# ✅ 升级 pip（此时仍用 root，没问题）
RUN python3 -m pip install --upgrade pip
RUN python3 -m pip install --upgrade wheel setuptools
# RUN python3 -m pip install 'litellm[proxy]==1.83.1'

# Go 工具
RUN go env -w GOPROXY=https://goproxy.cn,https://mirrors.aliyun.com/goproxy/,direct
RUN go install github.com/golangci/golangci-lint/cmd/golangci-lint@v1.53.3

# ===== 配置非root用户 =====
# 在mac上没问题，在win上不行
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && chown -R $USERNAME:$USERNAME /go /opt/venv

USER $USERNAME
# ===== Claude Code =====
# RUN npm install -g @anthropic-ai/claude-code
RUN curl -fsSL https://claude.ai/install.sh | bash

USER root
RUN ln -s /home/$USERNAME/.local/bin/claude /usr/local/bin/claude
RUN chmod 775 /usr/local/bin/claude
RUN chown root:vscode /usr/local/bin/claude


# chmod -R vscode:vscode /workspaces

RUN mkdir ~/.claude-code-router/
