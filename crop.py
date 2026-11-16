import ctypes

try:
  ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
  ctypes.windll.user32.SetProcessDPIAware()

import os
import time
import cv2
import mss
import numpy as np
import win32gui


def get_first_rok_window():
  found = []

  def cb(hwnd, _):
    if win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd):
      if "Rise of Kingdoms" in win32gui.GetWindowText(hwnd):
        rect = win32gui.GetClientRect(hwnd)
        left, top = win32gui.ClientToScreen(hwnd, (0, 0))
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if w > 200 and h > 200:
          found.append(
              {"hwnd": hwnd, "left": left, "top": top, "width": w, "height": h}
          )

  win32gui.EnumWindows(cb, None)
  return found[0] if found else None


TARGETS = [
    ("btn_alliance.png", "1. Cat icon 'Alliance' o menu duoi"),
    ("btn_war.png", "2. Cat icon 'War' (hai thanh kiem cheo)"),
    ("btn_join.png", "3. Cat o vuong dau '+' mau xanh la"),
    ("btn_new_troop.png", "4. Cat nut xanh duong 'New Troop'"),
    ("btn_march.png", "5. Cat nut mau vang 'MARCH'"),
    (
        "icon_march_active.png",
        "6. Cat o vuong xanh duong [\\] canh chu 1/5 (hoac 5/5)",
    ),
    ("march_full.png", "7. Cat gon dong chu '5/5' o goc phai"),
    (
        "btn_return.png",
        (
            "8. Bam chon 1 dao quan ngoai ban do: cat nut 'Return' (bieu tuong"
            " ngoi nha/mui ten ve thanh)"
        ),
    ),
    (
        "ap_status_label.png",
        "9. Mo avatar, cat nhan 'Action Points' kem bieu tuong binh",
    ),
    ("ap_plus.png", "10. Cat dau cong xanh tren thanh AP"),
    ("ap_modal_close.png", "11. Cat rieng dau X tren cua so Replenish Action Points"),
    ("ap_claim.png", "12. Cat nut CLAIM cua Daily Action Point Recovery"),
    ("ap_use.png", "13. Cat nut USE cua vat pham hoi AP"),
    ("ap_profile_close.png", "14. Cat dau X dong cua so avatar"),
]

with mss.mss() as sct:
  for filename, step_desc in TARGETS:
    status = "DA CO SAN" if os.path.exists(filename) else "CHUA CO"
    ans = input(
        f"\n>>> [{status}] {step_desc}\n"
        "    Bam ENTER de chup (hoac go 's' + Enter de giu nguyen/bo qua): "
    )
    if ans.strip().lower() == "s":
      continue

    win = get_first_rok_window()
    if not win:
      print("Khong tim thay cua so Rise of Kingdoms!")
      break

    ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
    ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
    win32gui.SetForegroundWindow(win["hwnd"])
    time.sleep(0.35)

    img = cv2.cvtColor(np.array(sct.grab(win)), cv2.COLOR_BGRA2BGR)
    win_title = f"Keo chuot chon {filename} roi bam ENTER"
    roi = cv2.selectROI(win_title, img, fromCenter=False, showCrosshair=True)
    cv2.destroyWindow(win_title)

    x, y, w, h = roi
    if w > 0 and h > 0:
      cv2.imwrite(filename, img[y : y + h, x : x + w])
      print(f"Da luu: {filename} ({w}x{h}px)")
    else:
      print(f"Giu nguyen / Bo qua {filename}")

print("\nHoan tat! Kiem tra cac file anh trong thu muc roi chay bot.py.")