# Auto Build-Flash-Verify Pipeline

Windows 本地 + Linux 编译 Server 全自动化流水线：
**远程编译 → 镜像同步 → 刷机 → 抓 log → 离线分析 → 邮件通知**

---

## 文件结构

```
auto_flash/
├── config.py        # 所有配置集中管理（只改这一个文件）
├── pipeline.py      # 主入口：Build → Flash → Verify → Notify
├── build.py         # 触发远程编译，轮询 watcher 状态
├── watcher.py       # Server 端：监听 trigger，执行编译 + cp
├── flash.py         # 刷机 + 刷机前后抓 log
├── verify.py        # 离线分析 log 目录，生成报告
├── img_finder.py    # 自动发现最新 img 目录，生成 flash plan
├── notify.py        # 通过本地 Outlook 发送 HTML 结果邮件
└── logs/            # 自动生成（log 目录 + pipeline 报告）
```

---

## 快速开始

### 1. 修改 config.py

```python
# ── Windows 本地路径 ──────────────────────────────────────
PLATFORM_TOOLS_DIR = r"C:\UPON\anroidtool\platform-tools"  # adb / fastboot
LOCAL_WORKSPACE    = r"C:\UPON\py_tool\auto_flash"

# ── 编译 Server ───────────────────────────────────────────
PROJECT_ROOT      = "/local/mnt/workspace/jiahduan/8845/0521"
BUILD_SERVER_USER = "jiahduan"

# ── 共享目录 ──────────────────────────────────────────────
WIN_SHARE_PATH    = r"C:\UPON\share_ai"          # Windows 挂载路径
SERVER_SHARE_PATH = "/local/mnt/workspace/jiahduan/share_win_ai"

# ── 邮件通知（可选）──────────────────────────────────────
NOTIFY_EMAIL = "you@example.com"   # None = 关闭
```

### 2. Server 端启动 watcher（只需一次）

```bash
# 在编译 Server 上执行
python watcher.py
```

### 3. Windows 端运行流水线

```bash
cd C:\UPON\py_tool\auto_flash

python pipeline.py               # 完整流程
python pipeline.py --skip-build  # 跳过编译，直接刷机 + 验证
python pipeline.py --flash-only  # 只刷机 + 验证
python pipeline.py --verify-only # 只分析已有 log
```

---

## 完整流程

```
Windows                              Server (watcher.py)
───────                              ───────────────────
pipeline.py
  │
  ├─ [Step 1] Build
  │    build.py 写 trigger.json  ──→  watcher 检测到 trigger
  │    轮询 status.json          ←──  执行编译 + cp_images.sh
  │                              ←──  写 status=done
  │    build 完成 ✓
  │
  ├─ [Step 2] Flash
  │    img_finder 自动找最新 img 目录
  │    ({WIN_SHARE_PATH}/{target}_{YYYYMMDD_HHMMSS}/)
  │
  │    flash.py:
  │      ① 抓 pre-flash log  → logs/{target}_pre_flash_{ts}/
  │      ② adb root
  │      ③ adb reboot bootloader
  │      ④ fastboot flash 各分区（按 FLASH_PARTITIONS 顺序）
  │      ⑤ fastboot reboot
  │      ⑥ adb wait-for-device（无固定等待，设备上线即继续）
  │      ⑦ 抓 post-flash log → logs/{target}_post_flash_{ts}/
  │
  ├─ [Step 3] Verify
  │    verify.py 离线分析 post-flash log 目录
  │    检测 PASS_KEYWORDS / ERROR_KEYWORDS
  │    生成 verify_report.txt
  │
  └─ [Step 4] Notify
       notify.py 通过本地 Outlook 发送 HTML 邮件
```

---

## img 目录自动发现

`cp_images.sh` 每次编译后将镜像 cp 到带时间戳的目录：

```
{WIN_SHARE_PATH}/
└── alor_20260707_143022/     ← {target}_{YYYYMMDD_HHMMSS}
    ├── abl.elf
    ├── boot.img
    ├── dtbo.img
    ├── system.img
    ├── persist.img
    ├── userdata.img
    └── full_update_ext4.zip  ← IMG_MAP 中 partition=None，跳过
```

`img_finder.py` 自动扫描 `WIN_SHARE_PATH`，取时间戳最新的目录。

查看当前 flash plan（不刷机）：

```bash
python img_finder.py
```

---

## log 目录结构

每次刷机自动生成两个 log 目录：

```
logs/
├── alor_pre_flash_20260707_143000/    ← 刷机前快照
│   ├── logcat.txt          (10s)
│   ├── dmesg.txt
│   ├── props.txt
│   ├── processes.txt
│   ├── meminfo.txt
│   ├── diskinfo.txt
│   ├── last_kmsg.txt
│   ├── journal.txt
│   ├── journal_boot.txt
│   ├── journal_kernel.txt
│   ├── journal_errors.txt
│   ├── systemd_failed.txt
│   └── verify_report.txt   ← verify.py 分析后生成
│
└── alor_post_flash_20260707_143500/   ← 刷机后完整 log
    ├── logcat.txt          (120s)
    ├── dmesg.txt / props.txt / ...
    ├── journal*.txt / systemd_failed.txt
    ├── bugreport.zip
    └── verify_report.txt
```

单独分析指定目录：

```bash
python verify.py                          # 自动找最新 post_flash 目录
python verify.py --dir logs/alor_post_flash_20260707_143500
python verify.py --pre  logs/alor_pre_flash_20260707_143000 \
                 --post logs/alor_post_flash_20260707_143500
```

---

## 刷机分区配置

`config.py` 中控制刷哪些分区及顺序：

```python
IMG_MAP = {
    "abl.elf":              "abl",
    "boot.img":             "boot",
    "dtbo.img":             "dtbo",
    "system.img":           "system",
    "persist.img":          "persist",
    "userdata.img":         "userdata",
    "full_update_ext4.zip": None,   # None = 跳过
}

FLASH_PARTITIONS = ["abl", "boot", "dtbo", "system", "persist", "userdata"]
```

只刷部分分区：

```python
FLASH_PARTITIONS = ["boot", "system"]
```

---

## 邮件通知

使用本地 Outlook 发送，无需配置 SMTP。

```python
# config.py
NOTIFY_EMAIL = "you@example.com"
# NOTIFY_EMAIL = ["a@example.com", "b@example.com"]  # 多人
# NOTIFY_EMAIL = None                                  # 关闭
```

邮件内容：
- Pipeline 各步骤 PASS / FAIL + 耗时
- Verify 摘要（boot 状态、error 数量）
- 错误日志（最多 20 条，含来源文件名）
- Pass 信号
- log 目录 / 报告路径

---

## 单模块使用

```bash
python build.py                    # 只触发编译
python flash.py                    # 只刷机（自动找最新 img）
python flash.py C:\path\to\imgs    # 刷机（指定 img 目录）
python verify.py                   # 分析最新 post_flash log
python img_finder.py               # 查看当前 flash plan
python notify.py                   # 发送测试邮件
```

---

## 切换项目

只需修改 `config.py` 顶部：

```python
PROJECT_ROOT   = "/local/mnt/workspace/jiahduan/新项目路径"
WIN_SHARE_PATH = r"C:\UPON\share_ai"
```

`BUILD_CMD`、`CP_CMD`、`IMG_MAP` 等全部自动跟随。