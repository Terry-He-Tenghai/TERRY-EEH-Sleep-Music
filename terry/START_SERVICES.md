# Terry EEG 项目启动指南

## 服务器启动功能说明

项目已集成远程 ACE-Step 服务器自动化管理功能，可通过前端界面一键启动远程服务器。

### 功能特性

- **自动化部署**：首次连接自动克隆代码并下载基础模型
- **智能检查**：验证项目完整性和模型权重
- **端口管理**：自动终止占用端口的进程
- **SSH 隧道**：建立本地端口转发，无需手动配置
- **实时日志**：完整的操作过程记录
- **安全设计**：密码不保存，仅用于本次连接

### 基础模型清单

系统会自动下载以下基础模型（约 10GB）：
- `acestep-v15-turbo`：主生成模型
- `vae`：变分自编码器
- `Qwen3-Embedding-0.6B`：文本编码器
- `acestep-5Hz-lm-1.7B`：语言模型

### 启动步骤

#### 1. 修复后端依赖（首次）

```bash
cd /Users/tenghai/Desktop/Terry_EEG_Project/new_code2/terry/backEnd
python3 -m uv sync --extra web
```

#### 2. 启动后端服务

```bash
cd /Users/tenghai/Desktop/Terry_EEG_Project/new_code2/terry/backEnd
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

#### 3. 启动前端开发服务器

```bash
cd /Users/tenghai/Desktop/Terry_EEG_Project/new_code2/terry/frontEnd
PATH=/Users/tenghai/.nvm/versions/node/v22.20.0/bin:$PATH pnpm dev
```

#### 4. 访问应用

打开浏览器访问：http://127.0.0.1:5173

点击顶部"服务器启动"标签，输入 SSH 信息：
- 服务器地址：`connect.nmb2.seetacloud.com`
- SSH 端口：`20389`
- 用户名：`root`
- 密码：`8L/UA47XnOoA`
- 远程端口：`8001`
- 本地端口：`8001`

点击"连接并启动"，系统会自动：
1. SSH 连接到服务器
2. 检查 `/root/autodl-tmp/ACE-Step-1.5` 项目
3. 如不存在，克隆 `https://github.com/ace-step/ACE-Step-1.5.git`
4. 检查模型权重，下载缺失文件
5. 终止占用 8001 端口的进程
6. 启动 ACE-Step API 服务
7. 建立 SSH 隧道到本地 8001 端口

完成后可在 http://127.0.0.1:8001/health 测试服务。

### 测试

```bash
cd /Users/tenghai/Desktop/Terry_EEG_Project/new_code2/terry/backEnd
.venv/bin/pytest tests/test_ace_server.py -v
```

### 故障排查

#### 依赖错误：`ModuleNotFoundError: No module named '_cffi_backend'`

重新同步依赖：
```bash
cd backEnd
python3 -m uv sync --extra web
```

#### SSH 连接超时

- 检查服务器地址和端口
- 确认用户名和密码正确
- 检查本地网络连接

#### 端口占用

查看占用进程：
```bash
lsof -nP -iTCP:8001 -sTCP:LISTEN
```

手动终止：
```bash
kill -TERM <PID>
```

### 架构说明

**后端模块**：`backEnd/ace_server_manager.py`
- SSH 连接管理（paramiko）
- 进程检测与终止（psutil）
- 远程命令执行
- 隧道生命周期管理

**前端组件**：`frontEnd/src/components/AceServerPanel.vue`
- 配置表单
- 状态轮询
- 实时日志显示
- 中英文双语

**API 端点**：
- `POST /api/ace-server/start`：启动服务器
- `POST /api/ace-server/stop`：停止服务
- `GET /api/ace-server/status`：查询状态

### 安全注意事项

1. **密码处理**：使用 Pydantic `SecretStr`，不记录到日志
2. **SSH 主机密钥**：首次连接自动信任（`AutoAddPolicy`）
3. **端口限制**：仅绑定 `127.0.0.1`，不暴露公网
4. **进程隔离**：仅终止确认占用指定端口的进程

### 未来改进

- [ ] SSH 密钥认证支持
- [ ] 主机密钥指纹验证
- [ ] 模型下载进度显示
- [ ] 多服务器配置保存
- [ ] 断线自动重连
