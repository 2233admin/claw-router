# Claw Router

智能 LLM API 路由器，提供统一的 OpenAI 兼容接口，支持多上游系统、协议转换、智能路由和熔断保护。

## 核心功能

- 🔄 **协议转换**: OpenAI ↔ Anthropic Messages API 双向转换
- 🧠 **智能路由**: 根据请求内容自动选择最佳模型（vision/code/reasoning/fast/default）
- 🛡️ **熔断保护**: 自动故障转移，3 次失败后打开熔断器，60 秒后恢复
- 🌐 **多上游支持**: 火山引擎 Ark + 本地 CLI 代理 + 内网 Hub 集群
- 📊 **监控仪表板**: 实时查看路由状态、熔断器状态、Hub 健康状态
- 🔒 **安全加固**: API key 验证、速率限制、请求大小限制

## 快速开始

### 1. 安装依赖

```bash
# 克隆项目
git clone https://github.com/2233admin/claw-router.git
cd claw-router

# 安装（Python 3.11+）
pip install -e .
```

### 2. 配置环境变量

```bash
# 复制配置模板
cp config/.env.example .env

# 编辑 .env 填入 API keys
# ARK_API_KEY=your_ark_key
# CLIPROXY_KEY=your_cliproxy_key
# HUB_*_AUTH=your_hub_auth_tokens
```

### 3. 配置路由规则

编辑 `config/routes.yaml`:

```yaml
routes:
  vision:    [ark:doubao-seed-2.0-pro]
  code:      [hub:deepseek, hub:gemini]
  reasoning: [hub:deepseek-think, hub:kimi]
  fast:      [hub:gemini-flash, hub:glm]
  default:   [hub:gemini, hub:qwen]

aliases:
  claude: "cli:claude-sonnet-4-6"
  deepseek: "hub:deepseek"
```

### 4. 配置上游服务

编辑 `config/hubs.yaml`:

```yaml
upstreams:
  ark:
    base: "https://ark.cn-beijing.volces.com/api/coding/v1"
    protocol: anthropic
    auth: "${ARK_API_KEY}"

hubs:
  deepseek:
    base: "http://10.10.0.3:8011"
    model: deepseek-chat
    auth: "${HUB_DEEPSEEK_AUTH}"
```

### 5. 启动服务

```bash
# 开发模式（自动重载）
claw-router serve --reload

# 生产模式
claw-router serve --port 3456 --host 0.0.0.0
```

服务启动后访问：
- API 端点: `http://localhost:3456/v1/chat/completions`
- 仪表板: `http://localhost:3456/dashboard`
- 健康检查: `http://localhost:3456/health`
- 监控指标: `http://localhost:3456/metrics`

## API 使用

### 基本请求

```bash
curl -X POST http://localhost:3456/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_api_key" \
  -d '{
    "model": "auto",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

### 指定模型

```bash
# 使用别名
curl ... -d '{"model": "deepseek", "messages": [...]}'

# 使用完整前缀
curl ... -d '{"model": "hub:deepseek", "messages": [...]}'
curl ... -d '{"model": "ark:doubao-seed-2.0-pro", "messages": [...]}'
curl ... -d '{"model": "cli:claude-sonnet-4-6", "messages": [...]}'
```

### 流式响应

```bash
curl ... -d '{
  "model": "auto",
  "messages": [...],
  "stream": true
}'
```

### 多模态（图片）

```bash
curl ... -d '{
  "model": "auto",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "What is in this image?"},
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
    ]
  }]
}'
```

## 智能路由

路由器会根据请求内容自动分类并选择最佳模型：

| 分类 | 触发条件 | 优先模型 |
|------|----------|----------|
| **vision** | 包含图片内容 | doubao-seed-2.0-pro |
| **code** | 代码关键词（code, debug, function, 写代码） | deepseek → gemini |
| **reasoning** | 推理关键词（analyze, think, 分析, 推理） | deepseek-think → kimi |
| **fast** | 简短文本 + 快速关键词（translate, hello） | gemini-flash → glm |
| **default** | 其他 | gemini → qwen |

## 熔断器

自动保护系统免受故障模型影响：

- **阈值**: 3 次失败后打开
- **冷却**: 60 秒后自动尝试恢复
- **降级**: 自动跳过打开的熔断器，选择下一个可用模型

查看熔断器状态：

```bash
curl http://localhost:3456/status
```

## CLI 工具

```bash
# 启动服务
claw-router serve --port 3456

# 显示路由表
claw-router status

# 检查所有 Hub 健康状态
claw-router health

# 部署到生产环境
claw-router deploy
```

## 配置说明

### 路由规则 (routes.yaml)

```yaml
routes:
  <capability>: [<model1>, <model2>, ...]  # 优先级列表

aliases:
  <short_name>: "<prefix>:<model_id>"      # 别名映射

no_vision:
  - "<model>"                              # 不支持视觉的模型

signals:
  <capability>: '<regex_pattern>'          # 分类正则表达式
```

### 上游配置 (hubs.yaml)

```yaml
upstreams:
  <name>:
    base: "<base_url>"
    protocol: "openai" | "anthropic"
    auth: "${ENV_VAR}"
    timeout: <seconds>

hubs:
  <name>:
    base: "<base_url>"
    model: "<model_id>"
    auth: "${ENV_VAR}"
```

### 环境变量 (.env)

```bash
# 火山引擎 Ark
ARK_API_KEY=your_ark_key

# 本地 CLI 代理
CLIPROXY_KEY=your_cliproxy_key

# Hub 认证（可选）
HUB_KIMI_AUTH=your_token
HUB_DEEPSEEK_AUTH=your_token
# ...
```

## 部署

### Systemd 服务

```bash
# 复制服务文件
sudo cp deploy/claw-router.service /etc/systemd/system/

# 启用并启动
sudo systemctl daemon-reload
sudo systemctl enable claw-router
sudo systemctl start claw-router

# 查看状态
sudo systemctl status claw-router

# 查看日志
sudo journalctl -u claw-router -f
```

### Docker 部署

```bash
# 构建镜像
docker build -t claw-router .

# 运行容器
docker run -d \
  --name claw-router \
  -p 3456:3456 \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/.env:/app/.env \
  claw-router
```

### 一键部署

```bash
# 部署到生产服务器（43.156.202.94）
claw-router deploy
```

## 监控

### 仪表板

访问 `http://localhost:3456/dashboard` 查看：
- 路由表和熔断器状态
- Hub 健康状态和延迟
- 实时刷新（10 秒）

### Prometheus 指标

访问 `http://localhost:3456/metrics` 获取：
- `claw_router_requests_total` - 总请求数
- `claw_router_request_duration_seconds` - 请求延迟
- `claw_router_errors_total` - 错误数
- `claw_router_breaker_open` - 熔断器状态

### 健康检查

```bash
curl http://localhost:3456/health
```

返回所有上游的健康状态和延迟。

## 故障排查

### 服务无法启动

```bash
# 检查配置文件
claw-router status

# 检查环境变量
cat .env

# 检查端口占用
lsof -i :3456
```

### Hub 连接失败

```bash
# 检查 Hub 健康状态
claw-router health

# 手动测试连接
curl http://10.10.0.3:8011/v1/models
```

### 熔断器频繁打开

```bash
# 查看熔断器状态
curl http://localhost:3456/status

# 检查上游日志
sudo journalctl -u claw-router -f | grep breaker
```

### 请求被拒绝

```bash
# 检查 API key
curl -H "Authorization: Bearer your_key" http://localhost:3456/v1/models

# 检查速率限制
# 默认：100 req/min per key
```

## 架构

```
┌─────────────────────────────────────────────────────┐
│                  客户端 (OpenAI 兼容)                 │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│              Claw Router (FastAPI)                   │
│                                                       │
│  [请求分类] → [模型选择] → [协议转换] → [上游调用]   │
│       ↓            ↓            ↓            ↓       │
│   正则匹配    熔断器检查   OpenAI↔Anthropic  httpx   │
│                                                       │
│  [熔断器] ← 失败追踪 ← [上游响应]                    │
│  [健康检查] ← 后台 ping ← [所有上游]                 │
└────────────────────┬────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
   ┌────▼──┐    ┌───▼───┐   ┌───▼────┐
   │  Ark  │    │  CLI  │   │  Hub   │
   │(火山) │    │(本地) │   │(内网)  │
   │Anthro │    │OpenAI │   │OpenAI  │
   └───────┘    └───────┘   └────────┘
```

## 开发

### 运行测试

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 测试覆盖率
pytest --cov=claw_router --cov-report=html
```

### 代码格式化

```bash
# 使用 ruff
ruff check src/
ruff format src/
```

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
