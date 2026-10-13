"""Remote ACE-Step server provisioning and tunnel management."""

import asyncio
import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

try:
    import paramiko
    import psutil
    DEPENDENCIES_AVAILABLE = True
except ImportError:
    DEPENDENCIES_AVAILABLE = False

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, SecretStr, field_validator

router = APIRouter(prefix="/api/ace-server", tags=["ace-server"])
logger = logging.getLogger("terry.ace_server")

REMOTE_PROJECT_PATH = "/root/autodl-tmp/ACE-Step-1.5"
REPO_URL = "https://github.com/ace-step/ACE-Step-1.5.git"
REQUIRED_MODELS = ["acestep-v15-turbo", "vae", "Qwen3-Embedding-0.6B", "acestep-5Hz-lm-1.7B"]


class ServerConfig(BaseModel):
    host: str = Field(pattern=r"^[a-zA-Z0-9\.\-]+$")
    port: int = Field(ge=1, le=65535)
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1)
    remote_port: int = Field(default=8001, ge=1024, le=65535)
    local_port: int = Field(default=8001, ge=1024, le=65535)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        if not re.match(r"^[a-zA-Z0-9\.\-]+$", value):
            raise ValueError("Invalid hostname")
        return value


@dataclass
class JobStatus:
    stage: Literal["idle", "connecting", "checking", "installing", "starting", "tunneling", "ready", "error"]
    message: str
    log: list[str]
    tunnel_pid: int | None = None
    server_pid: int | None = None


class ServerManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.job_id = 0
        self.status = JobStatus("idle", "未启动", [])
        self.worker: threading.Thread | None = None
        self.ssh_client: paramiko.SSHClient | None = None
        self.tunnel_process: subprocess.Popen | None = None
        self.stop_requested = False

    def get_status(self) -> dict:
        with self.lock:
            return {
                "stage": self.status.stage,
                "message": self.status.message,
                "log": self.status.log.copy(),
                "tunnel_pid": self.status.tunnel_pid,
                "server_pid": self.status.server_pid,
            }

    def _log(self, message: str):
        with self.lock:
            self.status.log.append(f"{time.strftime('%H:%M:%S')} {message}")
            logger.info(message)

    def _update_stage(self, stage: str, message: str):
        with self.lock:
            self.status.stage = stage
            self.status.message = message
        self._log(message)

    def start(self, config: ServerConfig) -> dict:
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise HTTPException(409, "服务器启动任务正在进行中")
            self.job_id += 1
            self.status = JobStatus("connecting", "正在连接...", [])
            self.stop_requested = False
            job_id = self.job_id
        
        self.worker = threading.Thread(
            target=self._run_provisioning,
            args=(job_id, config),
            daemon=True,
            name="ace-server-provisioning"
        )
        self.worker.start()
        return self.get_status()

    def stop(self):
        with self.lock:
            self.stop_requested = True
            if self.ssh_client:
                try:
                    self.ssh_client.close()
                except Exception:
                    pass
            if self.tunnel_process:
                try:
                    self.tunnel_process.terminate()
                    self.tunnel_process.wait(timeout=5)
                except Exception:
                    pass
        self._update_stage("idle", "已停止")

    def _run_provisioning(self, job_id: int, config: ServerConfig):
        try:
            self._provision(job_id, config)
        except Exception as exc:
            self._update_stage("error", f"失败: {exc}")
            logger.exception("Provisioning failed")

    def _provision(self, job_id: int, config: ServerConfig):
        # 1. 连接 SSH
        self._update_stage("connecting", f"正在连接 {config.host}:{config.port}...")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            client.connect(
                hostname=config.host,
                port=config.port,
                username=config.username,
                password=config.password.get_secret_value(),
                timeout=15,
                banner_timeout=15,
                auth_timeout=15
            )
        except Exception as exc:
            raise RuntimeError(f"SSH 连接失败: {exc}")
        
        with self.lock:
            if self.stop_requested or self.job_id != job_id:
                client.close()
                return
            self.ssh_client = client
        
        self._log("SSH 连接成功")

        # 2. 检查项目和模型
        self._update_stage("checking", "检查远程项目...")
        stdin, stdout, stderr = client.exec_command(f"test -d {REMOTE_PROJECT_PATH} && echo exists || echo missing")
        project_exists = stdout.read().decode().strip() == "exists"
        
        if not project_exists:
            self._update_stage("installing", "克隆项目代码...")
            stdin, stdout, stderr = client.exec_command(
                f"cd /root/autodl-tmp && git clone {REPO_URL} && echo done"
            )
            stdout.channel.recv_exit_status()
            output = stdout.read().decode()
            if "done" not in output:
                raise RuntimeError("克隆代码失败")
            self._log("代码克隆完成")
        
        # 检查模型
        self._update_stage("checking", "检查模型权重...")
        check_cmd = f"cd {REMOTE_PROJECT_PATH}/checkpoints && " + " && ".join(
            f"test -f {model}/model.safetensors && echo {model}-ok || echo {model}-missing"
            for model in REQUIRED_MODELS
        )
        stdin, stdout, stderr = client.exec_command(check_cmd)
        model_status = stdout.read().decode().strip().split("\n")
        missing = [line.replace("-missing", "") for line in model_status if "missing" in line]
        
        if missing:
            self._update_stage("installing", f"下载缺失模型: {', '.join(missing)}...")
            download_cmd = (
                f"cd {REMOTE_PROJECT_PATH} && "
                f"source .venv/bin/activate && "
                f"python -c \"from acestep.model_downloader import download_main_model; "
                f"download_main_model(force=False)\""
            )
            stdin, stdout, stderr = client.exec_command(download_cmd, timeout=600)
            stdout.channel.recv_exit_status()
            self._log("模型下载完成")

        # 3. 杀死占用端口的进程
        self._update_stage("starting", f"检查端口 {config.remote_port}...")
        stdin, stdout, stderr = client.exec_command(
            f"lsof -ti:{config.remote_port} 2>/dev/null || echo none"
        )
        pid_output = stdout.read().decode().strip()
        
        if pid_output and pid_output != "none":
            for pid in pid_output.split("\n"):
                if pid.isdigit():
                    self._log(f"杀死占用端口的进程 PID {pid}")
                    client.exec_command(f"kill -TERM {pid}")
                    time.sleep(1)

        # 4. 启动 ACE-Step 服务
        self._update_stage("starting", "启动 ACE-Step 服务...")
        start_cmd = (
            f"cd {REMOTE_PROJECT_PATH} && "
            f"nohup .venv/bin/acestep-api --host 127.0.0.1 --port {config.remote_port} "
            f"--lm-model-path acestep-5Hz-lm-1.7B "
            f"> ace-server-$(date +%Y%m%d-%H%M%S).log 2>&1 < /dev/null & echo $!"
        )
        stdin, stdout, stderr = client.exec_command(start_cmd)
        server_pid = stdout.read().decode().strip()
        
        if not server_pid.isdigit():
            raise RuntimeError("启动服务失败")
        
        self._log(f"服务已启动，PID: {server_pid}")
        time.sleep(3)  # 等待服务初始化

        # 5. 杀死本地占用端口的进程
        self._update_stage("tunneling", f"检查本地端口 {config.local_port}...")
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                for conn in proc.connections(kind='inet'):
                    if conn.status == 'LISTEN' and conn.laddr.port == config.local_port:
                        self._log(f"杀死本地占用端口的进程 PID {proc.pid}")
                        proc.terminate()
                        proc.wait(timeout=3)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # 6. 建立 SSH 隧道
        self._update_stage("tunneling", "建立 SSH 隧道...")
        tunnel_cmd = [
            "ssh", "-f", "-N",
            "-o", "ConnectTimeout=15",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-L", f"127.0.0.1:{config.local_port}:127.0.0.1:{config.remote_port}",
            "-p", str(config.port),
            f"{config.username}@{config.host}"
        ]
        
        tunnel = subprocess.Popen(
            tunnel_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        tunnel.stdin.write(f"{config.password.get_secret_value()}\n".encode())
        tunnel.stdin.flush()
        time.sleep(2)
        
        if tunnel.poll() is not None:
            raise RuntimeError("SSH 隧道建立失败")
        
        with self.lock:
            self.tunnel_process = tunnel
            self.status.tunnel_pid = tunnel.pid
            self.status.server_pid = int(server_pid)
        
        self._update_stage("ready", f"服务就绪，本地访问 http://127.0.0.1:{config.local_port}")


manager = ServerManager()


@router.post("/start")
async def start_server(config: ServerConfig):
    if not DEPENDENCIES_AVAILABLE:
        raise HTTPException(503, "服务器管理功能需要 paramiko 和 psutil 依赖，请运行: pip install paramiko psutil")
    return manager.start(config)


@router.post("/stop")
async def stop_server():
    if not DEPENDENCIES_AVAILABLE:
        raise HTTPException(503, "服务器管理功能需要 paramiko 和 psutil 依赖")
    manager.stop()
    return manager.get_status()


@router.get("/status")
async def get_status():
    if not DEPENDENCIES_AVAILABLE:
        return {"stage": "error", "message": "缺少依赖: paramiko, psutil", "log": [], "tunnel_pid": None, "server_pid": None}
    return manager.get_status()
