# Auto Build-Flash-Verify Pipeline v3.0
## 使用说明

---

## 目录结构

```
auto_flash/                   ← Windows 本地开发目录（源码）
    config.py                 ← 唯一需要手动修改的配置文件
    pipeline.py               ← 主入口
    watcher.py                ← Server 端守护进程
    watcher_client.py         ← Windows 端与 watcher 通信
    sync_code.py              ← sync 步骤
    cp_download.py            ← cp downloads 步骤
    build_abl.py              ← ABL build 步骤
    build_kernel.py           ← Kernel build 步骤
    build.py                  ← IMG build + cp images 步骤
    flash.py                  ← fastboot flash 步骤
    verify.py                 ← 开机验证步骤
    deploy.py                 ← 部署到 share 目录
    verify_deploy.py          ← 验证部署完整性
    sync_and_build_ok.sh      ← Server 端 build 脚本
    cp_download.sh            ← Server 端 downloads 拷贝脚本
    cp_images.sh              ← Server 端 images 拷贝脚本
    project.json              ← 共享配置（Windows/Server 共用）

share_ai_bak/                 ← Windows/Server 共享目录（deploy 输出）
    *.py / *.sh               ← 由 deploy.py 自动同步，不要手动修改
    project.json              ← 共享配置，sync 后自动更新 project_root
    watcher.log               ← Server 端实时日志
    status.json               ← 当前构建状态
```

---

## 首次配置

### 1. 修改 `auto_flash/config.py`

```python
PLATFORM_TOOLS_DIR = r"C:\UPON\anroidtool\platform-tools"  # adb/fastboot 路径
LOCAL_WORKSPACE    = r"C:\UPON\py_tool\auto_flash"          # 本项目路径
WIN_SHARE_PATH     = r"C:\UPON\share_ai_bak"                # 共享目录 Windows 挂载路径
```

> **注意**：`WIN_SHARE_PATH` 必须与 Server 端 `project.json` 里的 `server_share_path` 对应的 Windows 挂载路径一致。

### 2. 配置 `project.json`

```json
{
  "project_root":      "/local/mnt/workspace/.../Molokai_0713",
  "workspace_base":    "/local/mnt/workspace/.../8845",
  "server_share_path": "/local/mnt/workspace/.../share_win_ai_bak",
  "target":            "alor",
  "build_type":        "debug",
  "downloads_src":     "/local/mnt/workspace/.../0521/downloads",
  "project_name":      "Molokai",
  "files_to_copy":     ["abl.elf","boot.img","dtbo.img","system.img","persist.img","userdata.img","full_update_ext4.zip"],
  "lint_tools_dir":    "/local/mnt2/workspace/.../lint_tools",
  "sync_cmd":          "python {lint_tools_dir}/src/sync_scripts/sync.py . -t {target}_le ..."
}
```

### 3. 部署到共享目录

```bash
cd C:\UPON\py_tool\auto_flash
python deploy.py
python verify_deploy.py   # 验证 97/97 PASSED
```

### 4. Server 端启动 watcher

```bash
kill $(pgrep -f watcher.py) 2>/dev/null
cd /local/mnt/workspace/.../share_win_ai_bak
python3 -u watcher.py &
```

---

## Pipeline 使用方式

所有命令在 Windows 端执行，**从 share 目录启动**：

```bash
cd C:\UPON\share_ai_bak
python pipeline.py [选项]
```

### 完整流程

```bash
python pipeline.py --full
# sync -> cp_dl -> abl -> kernel -> img -> flash -> verify
```

### 跳过 sync（workspace 已存在）

```bash
python pipeline.py --skip-sync
# cp_dl -> abl -> kernel -> img -> flash -> verify

python pipeline.py --skip-sync --skip-cp-download
# abl -> kernel -> img -> flash -> verify
```

### 仅 sync

```bash
python pipeline.py --sync-only
# sync -> cp_dl

python pipeline.py --sync-only --skip-cp-download
# sync only
```

### 单步执行

```bash
python pipeline.py --cp-dl-only     # 仅 copy downloads
python pipeline.py --abl-only       # 仅 ABL build
python pipeline.py --kernel-only    # 仅 Kernel build
python pipeline.py                  # img -> flash -> verify（默认）
python pipeline.py --skip-build     # flash -> verify
python pipeline.py --flash-only     # flash -> verify
python pipeline.py --verify-only    # 仅验证
```

### 指定 img build 重试次数

```bash
python pipeline.py --full --img-retries 5
```

---

## 各步骤说明

| 步骤 | 脚本 | 执行位置 | 说明 |
|------|------|----------|------|
| sync | `sync_and_build_ok.sh -sync` | Server SHARE_DIR | repo sync + cherry-pick，创建新 workspace，更新 project.json |
| cp_dl | `cp_download.sh` | Server PROJECT_ROOT | 从 downloads_src 拷贝 downloads 到新 workspace |
| abl | `sync_and_build_ok.sh -abl` | Server PROJECT_ROOT | bazel build ABL |
| kernel | `sync_and_build_ok.sh -ker` | Server PROJECT_ROOT | build_with_bazel.py，产物输出到 bitbake 期望路径 |
| img | `sync_and_build_ok.sh -img` | Server PROJECT_ROOT | bitbake qti-multimedia-image |
| cp images | `cp_images.sh` | Server PROJECT_ROOT | 拷贝镜像到 SHARE_DIR/alor_TIMESTAMP/ |
| flash | `flash.py` | Windows 本地 | fastboot flash 所有分区 |
| verify | `verify.py` | Windows 本地 | adb 验证开机 + logcat |

---

## Kernel Build 路径说明

```
build_with_bazel.py 输出路径：
  kernel_platform/out/msm-kernel-alor_le-debug/
      dist/   ← KERNEL_PREBUILT_DISTDIR
      host/   ← merge-dtbs-gki-native SRC_URI

--out_dir="../out/msm-kernel-alor_le-debug"
  → 产物直接输出到 bitbake 期望路径
  → 不需要 cp 或 symlink

BUILD_WORKSPACE_DIRECTORY 必须内联注入：
  terminal 有（source set_bb_env.sh），watcher 子进程没有
```

---

## sh 文件部署机制

```
每次 trigger 到达 watcher 时：
  _ensure_sh_executable(project_root=trigger["project_root"])
    → 从 SHARE_DIR 把 *.sh cp 到 PROJECT_ROOT/
    → chmod +x
    → 保证执行的是最新版本的脚本

project_root 由 Windows 端在发送 trigger 时携带：
  _root = config.PROJECT_ROOT   ← sync 后 reload 的最新值
  trigger["project_root"] = _root
  → watcher cp sh 到正确的 workspace
  → cmd 也用同一个 workspace
  → 两者始终一致
```

---

## 常见问题

### watcher 没有响应
```bash
# Server 端检查
ps aux | grep watcher.py
# 重启
kill $(pgrep -f watcher.py)
cd /local/mnt/workspace/.../share_win_ai_bak
python3 -u watcher.py &
```

### bitbake reconnect 导致 img build 失败
- watcher 自动重试，最多 `BUILD_IMG_RETRIES`（默认 3）次
- 重试前清理 bitbake lock 文件

### libcec do_unpack 失败（shallow clone）
```bash
rm -rf .../downloads/git2/github.com.Pulse-Eight.libcec.git
# 重新触发 img build
```

### sync 后后续步骤用旧路径
- 确认 `pipeline.py` 从 `share_ai_bak/` 目录启动
- 确认 `auto_flash/config.py` 里 `WIN_SHARE_PATH = r"C:\UPON\share_ai_bak"`
- 重启 watcher（加载新版本）

---

## 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|----------|
| v1.0 | 2026-07-07 | 初始版本，基础 flash/verify 流程 |
| v2.0 | 2026-07-08 | 增加 pipeline，sync/build/cp 全流程 |
| v3.0 | 2026-07-13 | 修复 kernel 路径、sh 部署机制、project_root 传递、cp_images set -e bug |
