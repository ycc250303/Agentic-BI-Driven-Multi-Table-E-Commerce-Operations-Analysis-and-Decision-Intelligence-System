# MySQL 服务器部署流程

## 1 安装 Docker 和 Compose

```
sudo apt update
sudo apt install -y ca-certificates curl gnupg lsb-release

# 添加 Docker 官方 GPG key
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# 添加仓库
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

验证：

```
docker --version
docker compose version
```

## 2 创建目录

```
cd opt/
mkdir agentic_bi
cd agentic_bi
mkdir -p data conf init
```

* data：MySQL 数据持久化
* conf：自定义配置
* init：初始化 SQL（首次启动自动执行）

## 3 编写 docker-compose,yml

```
services:
  mysql:
    image: mysql:8.0
    container_name: mysql8
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: "agentic_bi"
      MYSQL_DATABASE: "agentic_bi"
      MYSQL_USER: "agentic_bi"
      MYSQL_PASSWORD: "agentic_bi"
      TZ: "Asia/Shanghai"
    ports:
      - "3306:3306"
    volumes:
      - ./data:/var/lib/mysql
      - ./conf:/etc/mysql/conf.d
      - ./init:/docker-entrypoint-initdb.d
    command: --default-authentication-plugin=mysql_native_password
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-agentic_bi!"]
      interval: 10s
      timeout: 5s
      retries: 10
```

## 4 启动服务


```
docker compose up -d
docker compose ps
docker compose logs -f mysql
```

看到 ready for connections 基本就成功了.

## 5 测试连接

## 6 常用运维命令

```
# 重启
docker compose restart mysql

# 停止
docker compose stop mysql

# 停止并删除容器（保留 data 数据）
docker compose down

# 查看日志
docker compose logs -f mysql
```