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

账号与库名以 compose 中的 `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` 为准（下文示例为 `agentic_bi`）。本机连 Docker 用 `127.0.0.1`；远程把主机换成云服务器公网 IP，并确认 3306 已监听、安全组已放行。

```
# 容器是否在跑、3306 是否在听
docker compose ps
ss -lntp | grep 3306

# 容器内
docker exec -it mysql8 mysql -uagentic_bi -pagentic_bi -e "SELECT VERSION(); SHOW DATABASES;"

# 宿主机 / 本机客户端（需已安装 mysql client）
mysql -h 127.0.0.1 -P 3306 -u agentic_bi -pagentic_bi -e "SELECT 1 AS ok;"

# 远程（把 HOST 换成公网 IP）
mysql -h HOST -P 3306 -u agentic_bi -pagentic_bi -e "SELECT 1 AS ok;"

# 项目脚本（读取仓库根目录 .env 的 AGENTIC_BI_DB_*）
python utils/setup.py init
```

`SELECT 1` 或打印出版本 / 库列表即连接成功。若出现 `Connection refused`，先查容器和 `ss`，再查云安全组是否放行 3306。

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