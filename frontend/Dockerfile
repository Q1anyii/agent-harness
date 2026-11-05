# ============================================================
# Dockerfile（frontend/）— 前端多阶段构建：node 构建 dist → nginx 自包含镜像
# 让「docker compose up -d --build」一步到位：宿主只需 Docker，无需安装 Node
# 构建产物只存在于中间层（stage 1），最终镜像只含 nginx + dist + nginx.conf
# 注意：build context 为项目根（compose 中 context: . + dockerfile: frontend/Dockerfile），
#       所以本文件内 COPY 路径以项目根为基准
# 国内构建加速：docker build --build-arg NPM_REGISTRY=https://registry.npmmirror.com .
# ============================================================

# ---- Stage 1：构建前端产物 ----
FROM node:20-alpine AS frontend-build

ARG NPM_REGISTRY=https://registry.npmjs.org

WORKDIR /app

# 先只复制依赖清单，利用 Docker 缓存层（源码变更不触发 npm ci）
COPY frontend/package.json frontend/package-lock.json ./
RUN npm config set registry ${NPM_REGISTRY} && npm ci

# 再复制源码并构建（tsc 类型检查 + vite build → dist/）
COPY frontend/ ./
RUN npm run build

# ---- Stage 2：nginx 自包含镜像（静态托管 + API 反代）----
FROM nginx:1.27-alpine

# 只拷构建产物与 nginx 配置，不拷源码/node_modules
COPY --from=frontend-build /app/dist /usr/share/nginx/html
COPY deploy/nginx/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
