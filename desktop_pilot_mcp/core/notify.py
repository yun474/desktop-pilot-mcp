"""Windows 右下角通知（Toast）。借用 Windows PowerShell 自带的应用标识，无需注册快捷方式。"""

from __future__ import annotations

from xml.sax.saxutils import escape

from .shell import ps_quote, run_powershell

# Windows PowerShell 的 AppUserModelID，系统默认已注册
_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def send_toast(title: str, message: str) -> None:
    xml = (
        '<toast><visual><binding template="ToastGeneric">'
        f"<text>{escape(title)}</text><text>{escape(message)}</text>"
        "</binding></visual></toast>"
    )
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null\n"
        "$doc = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
        f"$doc.LoadXml({ps_quote(xml)})\n"
        "$toast = New-Object Windows.UI.Notifications.ToastNotification $doc\n"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier({ps_quote(_APP_ID)}).Show($toast)\n"
    )
    result = run_powershell(script, timeout=15)
    if result.exit_code != 0 or result.timed_out:
        raise RuntimeError(f"发送通知失败：{result.stderr or result.stdout or '超时'}")
