# Auto Flash Pipeline v2.0 — 使用说明

## 概述

Auto Flash Pipeline 是一套自动化构建、烧录、验证工具，运行在 **Windows 客户端**，通过共享目录与 **Linux 编译服务器（Server）** 通信，完成从代码同步到设备验证的完整流程。

```
Windows (pipeline.py)
    │  trigger.json / status.json
    ▼
共享目录 (share_ai / share_win_ai)
    │
    ▼
Server (watcher.py) ──► sync / build / cp
    │
    ▼
Windows (flash.py / verify.py) ──► ADB / Fastboot
```

---

## 目录结构

```
auto_flash/                   # Windows 工作目录
├── config.py                 # [必须修改] 本地路径 & 参数配置
├── pipeline.py               # 主入口：完整流程控制
├── watcher_client.py         # 与 Server watcher 通信
├── build.py                  # img 编译触发（含 cp_images）
├── build_abl.py              # ABL 编译触发
├── build_kernel.py           # Kernel 编译触发
├── sync_code.py              # 代码同步触发
├── cp_download.py            # downloads 目录复制触发
├── cp_img.py                 # 手动触发 cp_images
├── flash.py                  # 设备烧录
├── verify.py                 # 设备验证
├── notify.py                 # 邮件通知
├── img_finder.py             # 共享目录镜像查找
├── deploy.py                 # 部署到共享目录
├── verify_deploy.py          # 部署验证
└── ota_flash_verify.py       # OTA 烧录验证

share_ai/                     # 共享目录（Windows 挂载路径）
├── project.json              # [必须修改] 项目配置（双端共享）
├── watcher.py                # Server 端守护进程
├── sync_and_build_ok.sh      # Server 端编译脚本
├── cp_images.sh              # Server 端镜像复制脚本
├── cp_download.sh            # Server 端 downloads 复制脚本
├── trigger.json              # Windows -> Server 触发信号
├── status.json               # Server -> Windows 状态反馈
└── watcher.log               # Server 端实时日志
```

---

## 快速开始

### 第一步：修改 config.py

```python
# Windows 本地路径
PLATFORM_TOOLS_DIR = r"C:\your\platform-tools"   # adb.exe / fastboot.exe 所在目录
LOCAL_WORKSPACE    = r"C:\your\auto_flash"        # 本项目目录
WIN_SHARE_PATH     = r"C:\your\share_ai"          # 共享目录 Windows 挂载路径
```

### 第二步：修改 project.json

```json
{
  "project_root":      "/server/path/to/workspace",
  "downloads_src":     "/server/path/to/reference/downloads",
  "workspace_base":    "/server/path/to/workspace/parent",
  "server_share_path": "/server/path/to/share_dir",
  "target":            "alor",
  "build_type":        "debug",
  "project_name":      "MyProject",
  "files_to_copy": ["abl.elf", "boot.img", "dtbo.img", "system.img",
                    "persist.img", "userdata.img", "full_update_ext4.zip"],
  "lint_tools_dir":    "/server/path/to/lint_tools",
  "sync_cmd":          "python {lint_tools_dir}/sync.py . -t {target}_le ..."
}
```

### 第三步：部署到共享目录

```bash
# Windows
python deploy.py
python verify_deploy.py   # 验证部署，94/94 PASSED 为正常
```

### 第四步：启动 Server 端 watcher

```bash
# Server (Linux)
cd /server/path/to/share_dir
python watcher.py
```

---

## pipeline.py 使用方法

### 完整流程

```bash
# 完整串行流程：sync -> cp-dl -> abl -> kernel -> img -> flash -> verify
python pipeline.py --full
```

### 跳过 sync（workspace 已存在）

```bash
# cp-dl(force) -> abl -> kernel -> img -> flash -> verify
python pipeline.py --skip-sync
```

### 仅同步

```bash
python pipeline.py --sync-only                  # sync -> cp-dl
python pipeline.py --sync-only --skip-cp-download  # 仅 sync
```

### 单步执行

```bash
python pipeline.py --cp-dl-only     # 仅复制 downloads 目录
python pipeline.py --abl-only       # 仅编译 ABL
python pipeline.py --kernel-only    # 仅编译 Kernel
```

### 跳过编译，直接烧录

```bash
python pipeline.py --skip-build     # flash -> verify（使用已有镜像）
python pipeline.py --flash-only     # 同上
python pipeline.py --verify-only    # 仅验证
```

### img 编译重试次数

```bash
# 默认使用 config.BUILD_IMG_RETRIES = 3
python pipeline.py --skip-sync --img-retries 5   # 最多重试 5 次
python pipeline.py --skip-sync --img-retries 1   # 不重试
```

---

## 单独执行各步骤

```bash
python sync_code.py                  # 代码同步
python cp_download.py                # 复制 downloads（不覆盖）
python cp_download.py --force        # 强制覆盖已有 downloads
python build_abl.py                  # ABL 编译
python build_kernel.py               # Kernel 编译
python build.py                      # img 编译 + cp_images
python cp_img.py                     # 仅 cp_images（已编译）
python flash.py                      # 烧录设备
python verify.py                     # 验证设备
```

---

## 流程图

```
--full:
  sync -> cp-dl -> abl -> kernel -> img build -> cp_images -> flash -> verify

--skip-sync:
  cp-dl(force) -> abl -> kernel -> img build -> cp_images -> flash -> verify

--sync-only:
  sync -> cp-dl

--abl-only:
  abl

--kernel-only:
  kernel

--skip-build / --flash-only:
  flash -> verify

--verify-only:
  verify
```

---

## 配置参数说明

### config.py 可调参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `CP_CHOICE` | `"0"` | cp_images 多候选时自动选第几个（0-based），`None` 为手动输入 |
| `BUILD_IMG_RETRIES` | `3` | img 编译 bitbake reconnect 时最大重试次数 |
| `CP_DOWNLOAD_FORCE` | `False` | 是否强制覆盖已有 downloads 目录 |
| `FASTBOOT_WAIT_SEC` | `15` | fastboot 等待设备超时秒数 |
| `LOGCAT_DURATION` | `120` | logcat 采集时长（秒） |
| `DEVICE_SERIAL` | `None` | 指定设备序列号，`None` 为自动选择 |
| `NOTIFY_EMAIL` | `"..."` | 流程完成后邮件通知地址 |

### project.json 字段说明

| 字段 | 说明 |
|---|---|
| `project_root` | Server 端当前 workspace 绝对路径（sync 后自动更新） |
| `downloads_src` | 参考项目的 downloads 目录（cp_download 的源） |
| `workspace_base` | workspace 父目录（sync 时在此创建新目录） |
| `server_share_path` | Server 端共享目录绝对路径 |
| `target` | 编译目标，如 `alor` |
| `build_type` | `debug` 或 `perf` |
| `project_name` | 项目名称前缀（sync 时用于命名新 workspace） |
| `files_to_copy` | cp_images 需要复制的镜像文件列表 |
| `lint_tools_dir` | lint_tools 工具目录（sync_cmd 模板变量） |
| `sync_cmd` | 同步命令模板，支持 `{lint_tools_dir}` `{target}` 占位符 |

---

## sh 脚本执行机制

每次 watcher 收到 trigger 时，先把 `SHARE_DIR/*.sh` 复制到 `PROJECT_ROOT/`，再 chmod +x，然后从 `PROJECT_ROOT` 执行：

```
trigger 到达
  -> _ensure_sh_executable()
     -> cp SHARE_DIR/sync_and_build_ok.sh  -> PROJECT_ROOT/
     -> cp SHARE_DIR/cp_images.sh          -> PROJECT_ROOT/
     -> cp SHARE_DIR/cp_download.sh        -> PROJECT_ROOT/
     -> chmod +x PROJECT_ROOT/*.sh
  -> 执行命令（从 PROJECT_ROOT）
```

**例外：SYNC 步骤**
sync 时 workspace（PROJECT_ROOT）还不存在，sh 脚本从 `SHARE_DIR` 执行。sync 完成后 watcher 自动把 sh 文件 cp 到新建的 workspace，后续步骤从 PROJECT_ROOT 执行。

| 步骤 | sh 执行路径 | 原因 |
|---|---|---|
| sync | `SHARE_DIR/sync_and_build_ok.sh` | workspace 尚未创建 |
| abl / kernel / img | `PROJECT_ROOT/sync_and_build_ok.sh` | 已 cp，从项目目录执行 |
| cp_images | `PROJECT_ROOT/cp_images.sh` | 已 cp |
| cp_download | `PROJECT_ROOT/cp_download.sh` | 已 cp |

---

## watcher.py 工作机制

```
Server 端 watcher 轮询 trigger.json：

trigger 类型          处理路径              特性
─────────────────────────────────────────────────────
script_cmd           handle_script         无 retry，无 bitbake 检测
                     (cp_download 专用)

build_cmd (无cp_cmd) handle_trigger        retry=1，无 bitbake 检测
                     (sync/abl/kernel)

build_cmd (有cp_cmd) handle_trigger        retry=N，有 bitbake 检测
                     (img build)           build 完成后执行 cp_images
```

### 状态流转

```
idle -> building -> copying -> done
                 -> error
```

---

## 编译产物路径说明

### Kernel 编译

```
build_with_bazel.py 输出（固定）：
  kernel_platform/out/msm-kernel-{TARGET}_le-{BUILD_TYPE}_defconfig/dist/

bitbake 期望路径：
  src/kernel-X.XX/out/msm-kernel-{TARGET}_le-{BUILD_TYPE}_defconfig/dist/

sync_and_build_ok.sh 自动将产物 cp -rL 到 bitbake 期望路径。
```

### cp_images 输出

```
Server 端：{server_share_path}/{TARGET}_{TIMESTAMP}/
Windows 端：{WIN_SHARE_PATH}/{TARGET}_{TIMESTAMP}/   （通过共享目录访问）
```

---

## 常见问题

**Q: watcher 没有响应 trigger**
- 检查 Server 端 `watcher.py` 是否在运行
- 检查共享目录挂载是否正常
- 查看 `share_ai/watcher.log`

**Q: cp_download 秒过**
- `--skip-sync` 模式下自动加 `--force` 强制覆盖，属正常行为
- 单独执行时加 `--force`：`python cp_download.py --force`

**Q: img 编译 bitbake reconnect 失败**
- 增加重试次数：`python pipeline.py --skip-sync --img-retries 5`
- 或修改 `config.BUILD_IMG_RETRIES`

**Q: cp_images 找到多个候选目录**
- 默认 `CP_CHOICE = "0"` 自动选第一个
- 修改 `config.CP_CHOICE` 指定其他候选

**Q: kernel 编译产物找不到**
- `sync_and_build_ok.sh` 会自动 `cp -rL` 到 bitbake 期望路径
- 查看 watcher.log 中 `Kernel dist (bitbake)` 行确认路径

---

## 版本历史

| 版本 | 说明 |
|---|---|
| v2.0 | cp_download 独立 script 路径；stdbuf 移除；bitbake 检测仅限 img；prompt 检测仅限 COPY；img-retries 参数；kernel dist 路径修复；cp_images 乱码修复 |
| v1.0 | 初始版本 |