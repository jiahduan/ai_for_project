# =============================================================================
# notify.py -- Send HTML email via local Outlook (win32com)
# =============================================================================

from datetime import datetime
from pathlib import Path
from config import NOTIFY_EMAIL, LOG_DIR


def _recipients():
    if not NOTIFY_EMAIL:
        return []
    if isinstance(NOTIFY_EMAIL, str):
        return [NOTIFY_EMAIL]
    return list(NOTIFY_EMAIL)


# =============================================================================
# Color palette -- single source of truth, no hex elsewhere in this file
# =============================================================================

_COLORS = {
    "PASS":  ("#1a7a1a", "#e6f4e6"),
    "FAIL":  ("#b30000", "#fde8e8"),
    "ERROR": ("#b30000", "#fde8e8"),
    "WARN":  ("#7a5c00", "#fff8e1"),
    "SKIP":  ("#555555", "#f0f0f0"),
    "INFO":  ("#003580", "#e8f0fe"),
}
_DEFAULT_COLOR = ("#333333", "#eeeeee")

_UI = {
    "body_text":      "#222222",
    "section_text":   "#333333",
    "section_border": "#dddddd",
    "muted":          "#555555",
    "mono_label":     "#888888",
    "header_bg":      "",
    "page_bg":        "",
    "card_bg":        "",
    "card_border":    "",
    "footer_bg":      "",
    "footer_text":    "#aaaaaa",
    "table_stripe":   "",
    "elapsed":        "#999999",
}


def _fg(label):
    return _COLORS.get(label.upper(), _DEFAULT_COLOR)[0]
def _bg(label):
    return _COLORS.get(label.upper(), _DEFAULT_COLOR)[1]

def _status(ok):
    if isinstance(ok, str):
        return ok.upper()   # already "PASS"/"FAIL"/"SKIP"
    return "PASS" if ok else "FAIL"

def _fmt_elapsed(seconds):
    s = int(seconds)
    if s >= 3600:
        return "{}h {:02d}m {:02d}s".format(s // 3600, (s % 3600) // 60, s % 60)
    if s >= 60:
        return "{}m {:02d}s".format(s // 60, s % 60)
    return "{:.1f}s".format(seconds)

# =============================================================================
# HTML primitives -- all colors via _fg/_bg/_UI
# =============================================================================

def _badge(label):
    return (
        '<span style="color:{fg};font-weight:bold;font-family:monospace;">'
        '[{label}]</span>'
    ).format(fg=_fg(label), label=label.upper())


def _colored(text, label):
    return '<span style="color:{fg};font-weight:bold;">{text}</span>'.format(
        fg=_fg(label), text=text)


def _section(title, icon=""):
    return (
        "<div style='margin:24px 0 8px;'>"
        "<span style='font-size:14px;font-weight:bold;color:{text};'>{icon}{title}</span>"
        "<hr style='margin:4px 0 0;border:none;border-top:2px solid {border};'/>"
        "</div>"
    ).format(
        text=_UI["section_text"],
        border=_UI["section_border"],
        icon=icon + "&nbsp;" if icon else "",
        title=title,
    )


def _step_row(step_name, status, elapsed, stripe=False):
    bg = _UI["table_stripe"] if stripe else _UI["card_bg"]
    return (
        "<tr>"
        "<td style='padding:7px 12px;width:80px;'>{badge}</td>"
        "<td style='padding:7px 12px;font-weight:500;'>{name}</td>"
        "<td style='padding:7px 12px;text-align:right;color:{ec};"
        "font-family:monospace;font-size:12px;'>{elapsed}</td>"
        "</tr>"
    ).format(bg=bg, badge=_badge(_status(status)), name=step_name,
             ec=_UI["elapsed"], elapsed=_fmt_elapsed(elapsed))


def _kv_row(key, value_html, stripe=False):
    bg = _UI["table_stripe"] if stripe else _UI["card_bg"]
    return (
        "<tr>"
        "<td style='padding:6px 12px;color:{muted};width:140px;'>{key}</td>"
        "<td style='padding:6px 12px;'>{value}</td>"
        "</tr>"
    ).format(bg=bg, muted=_UI["muted"], key=key, value=value_html)


def _log_line(fname, line, label):
    return (
        "<tr>"
        "<td style='font-family:monospace;font-size:12px;color:{lc};"
        "white-space:nowrap;padding:2px 12px 2px 0;vertical-align:top;'>[{fname}]</td>"
        "<td style='font-family:monospace;font-size:12px;color:{fc};"
        "padding:2px 0;word-break:break-all;'>{line}</td>"
        "</tr>"
    ).format(lc=_UI["mono_label"],
             fname=fname, fc=_fg(label), line=line[:150])


def _path_row(label, value):
    return (
        "<div style='font-family:monospace;font-size:12px;margin:4px 0;"
        "padding:4px 8px;background:{bg};border-radius:3px;'>"
        "<span style='color:{muted};display:inline-block;width:70px;'>{label}</span>"
        "<span style='color:{text};'>{value}</span>"
        "</div>"
    ).format(bg=_UI["table_stripe"], muted=_UI["muted"],
             text=_UI["body_text"], label=label, value=value)

# =============================================================================
# Build HTML
# =============================================================================

def _build_html(steps, verify_result, target, report_path=None):
    total_ok      = all(s in ("PASS", "SKIP") for _, s, _ in steps)
    timestamp     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    errors        = verify_result.get("errors", [])
    passes        = verify_result.get("passes", [])
    overall       = _status(total_ok)
    verify_ok     = _status(verify_result.get("ok", False))
    boot_ok       = verify_result.get("boot_completed", False)
    total_elapsed = sum(e for _, _, e in steps)

    H = []   # html parts

    # Document wrapper
    H.append(
        "<html><body style='font-family:Arial,sans-serif;font-size:13px;"
        "color:" + _UI["body_text"] + ";margin:0;padding:20px;'>"
        "<div style='max-width:680px;margin:0 auto;'>"
    )

    # Title bar
    H.append(
        "<div style='border-top:4px solid {border};"
        "border-radius:6px 6px 0 0;padding:16px 20px 12px;'>"
        "<div style='font-size:20px;font-weight:bold;color:{text};'>"
        "&#128640;&nbsp; Build-Flash-Verify Report</div>"
        "<div style='margin-top:6px;font-size:13px;color:{muted};'>"
        "Target: <strong>{target}</strong>&nbsp;&nbsp;|&nbsp;&nbsp;"
        "{ts}&nbsp;&nbsp;|&nbsp;&nbsp;"
        "Total: <strong>{elapsed}</strong>"
        "</div></div>".format(
            hbg=_UI["header_bg"], border=_fg(overall),
            text=_UI["section_text"], muted=_UI["muted"],
            target=target, ts=timestamp, elapsed=_fmt_elapsed(total_elapsed),
        )
    )

    # Overall result banner
    H.append(
        "<div style='border-left:4px solid {border};"
        "padding:10px 20px;'>"
        "<span style='font-size:15px;font-weight:bold;color:{fg};'>"
        "{badge}&nbsp; Pipeline {overall}"
        "</span></div>".format(
            bg=_bg(overall), border=_fg(overall), fg=_fg(overall),
            badge=_badge(overall), overall=overall,
        )
    )

    # Main content card
    H.append(
        "<div style='background:{bg};border:1px solid {border};"
        "border-top:none;border-radius:0 0 6px 6px;padding:16px 20px;'>".format(
            bg=_UI["card_bg"], border=_UI["card_border"],
        )
    )

    # Pipeline Steps
    H.append(_section("Pipeline Steps", "&#9654;"))
    H.append("<table style='border-collapse:collapse;width:100%;'>")
    for i, (sname, status, elapsed) in enumerate(steps):
        H.append(_step_row(sname, status, elapsed, stripe=(i % 2 == 1)))
    H.append("</table>")

    # Verify Summary
    H.append(_section("Verify Summary", "&#128203;"))
    H.append("<table style='border-collapse:collapse;width:100%;'>")
    H.append(_kv_row("Status",         _badge(verify_ok),                             stripe=False))
    H.append(_kv_row("Boot completed", _badge("PASS") if boot_ok else _badge("WARN"), stripe=True))
    H.append(_kv_row("Errors",
        _colored(str(len(errors)), "ERROR") if errors else _colored("0", "PASS"),      stripe=False))
    H.append(_kv_row("Pass signals",
        _colored(str(len(passes)), "PASS")  if passes else _colored("0", "WARN"),      stripe=True))
    H.append("</table>")

    # Pass Signals
    if passes:
        H.append(_section("Pass Signals", "&#10003;"))
        H.append("<table style='border-collapse:collapse;width:100%;'>")
        for fname, line in passes[:5]:
            H.append(_log_line(fname, line, "PASS"))
        H.append("</table>")

    # Errors
    if errors:
        limit       = min(len(errors), 20)
        err_title   = (
            "Errors &nbsp;<span style='font-size:12px;font-weight:normal;color:"
            + _UI["muted"] + ";'>(" + str(limit) + " / " + str(len(errors)) + " shown)</span>"
        )
        H.append(_section(err_title, "&#10007;"))
        H.append("<table style='border-collapse:collapse;width:100%;'>")
        for fname, line in errors[:limit]:
            H.append(_log_line(fname, line, "ERROR"))
        H.append("</table>")
        if len(errors) > limit:
            H.append(
                "<div style='color:" + _UI["muted"] + ";font-size:12px;margin-top:6px;'>"
                "&#8230; and " + str(len(errors) - limit) + " more error(s)"
                " &mdash; see log directory for full details.</div>"
            )

    # Output Files
    log_dir = verify_result.get("log_dir")
    if log_dir or report_path:
        H.append(_section("Output Files", "&#128193;"))
        if log_dir:
            H.append(_path_row("Log dir", log_dir))
        if report_path:
            H.append(_path_row("Report", str(report_path)))

    # Close main card
    H.append("</div>")

    # Footer
    H.append(
        "<div style='margin-top:12px;padding:10px 20px;"
        "border-radius:4px;"
        "font-size:11px;color:" + _UI["footer_text"] + ";text-align:center;'>"
        "This email was generated automatically by the Build-Flash-Verify pipeline."
        "&nbsp;&nbsp;|&nbsp;&nbsp;" + timestamp +
        "</div>"
    )

    # Close wrapper
    H.append("</div></body></html>")

    return "\n".join(H)


# =============================================================================
# Send
# =============================================================================

def send_notify(steps, verify_result, target="device", report_path=None):
    recipients = _recipients()
    if not recipients:
        print("[NOTIFY] NOTIFY_EMAIL not set, skipping.")
        return False

    total_ok  = all(s in ("PASS", "SKIP") for _, s, _ in steps)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject   = "[{}] Build-Flash-Verify -- {} {}".format(
        _status(total_ok), target, timestamp)
    html_body = _build_html(steps, verify_result, target, report_path)

    try:
        import win32com.client
        outlook       = win32com.client.Dispatch("Outlook.Application")
        mail          = outlook.CreateItem(0)
        mail.To       = "; ".join(recipients)
        mail.Subject  = subject
        mail.HTMLBody = html_body
        mail.Send()
        print("[NOTIFY] Email sent -> {}".format(", ".join(recipients)))
        return True
    except Exception as e:
        print("[NOTIFY] Failed to send email: {}".format(e))
        return False


if __name__ == "__main__":
    from img_finder import find_latest_img_dir
    img_dir = find_latest_img_dir()
    target  = img_dir.name.rsplit("_", 2)[0] if img_dir else "device"
    log_dir = str(Path(LOG_DIR) / "{}_post_flash_test".format(target))
    test_steps = [
        ("Remote Build", True,  7200.0),
        ("Flash Device", True,    45.0),
        ("Verify",       False,    5.0),
    ]
    test_verify = {
        "ok":             False,
        "boot_completed": True,
        "errors":         [
            ("logcat.txt",         "FATAL EXCEPTION in com.example.app"),
            ("journal_errors.txt", "kernel: BUG: unable to handle NULL pointer"),
        ],
        "passes":         [("logcat.txt", "Boot completed")],
        "log_dir":        log_dir,
    }
    send_notify(test_steps, test_verify, target=target)