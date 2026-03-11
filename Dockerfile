FROM python:3.13-slim

WORKDIR /app

# 复制项目文件
COPY pyproject.toml ./
COPY src/ ./src/
COPY config/ ./config/

# 安装依赖
RUN pip install --no-cache-dir -e .

# 暴露端口
EXPOSE 3456

# 启动命令
CMD ["claw-router", "serve", "--host", "0.0.0.0", "--port", "3456"]
