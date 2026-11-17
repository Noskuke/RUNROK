import ctypes
import re
import shutil

# Khóa tỷ lệ DPI Windows (Scale 100%/125%/150%) để tọa độ chuột khớp 100%
try:
  ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
  ctypes.windll.user32.SetProcessDPIAware()

from datetime import datetime
import os
import random
import threading
import time
import tkinter as tk
import cv2
import mss
import numpy as np
import pyautogui
import pytesseract
import win32con
import win32gui

# Vẩy chuột thật nhanh lên góc trên cùng bên trái màn hình (0, 0) để dừng khẩn cấp
pyautogui.FAILSAFE = True

# --- CẤU HÌNH ---
SCAN_MIN = 30  # Thời gian chờ tối thiểu giữa 2 lần quét của 1 tab (giây)
SCAN_MAX = 60  # Thời gian chờ tối đa giữa 2 lần quét của 1 tab (giây)
FULL_QUEUE_PAUSE_MIN = 2 * 60
FULL_QUEUE_PAUSE_MAX = 5 * 60
NO_RALLY_PAUSE_MIN = 2 * 60
NO_RALLY_PAUSE_MAX = 3 * 60
MAX_WAR_LIST_SCROLLS = 6
MAX_RALLIES_PER_SCAN = 5
MAX_RALLY_DISTANCE_KM = 45
RALLY_SCROLL_SETTLE_MIN = 1.5
RALLY_SCROLL_SETTLE_MAX = 2.0
AP_LOW_THRESHOLD = 0.25
AP_FULL_THRESHOLD = 0.98
AP_AVATAR_CLICK_RATIO = (0.02355, 0.04149)
AP_PROFILE_CLOSE_ROI = (0.22, 0.0, 0.32, 0.08)
AP_MODAL_CLOSE_ROI = (0.68, 0.17, 0.80, 0.29)
MAX_AP_USE_CLICKS = 30
AUTO_CASCADE = (
    True  # True: Tự xếp các tab thành bậc thang | False: Giữ vị trí hiện tại
)
TESSERACT_PATH = shutil.which("tesseract") or (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

REQUIRED_TEMPLATES = [
    "icon_world_map.png",
    "btn_to_map.png",
    "btn_alliance.png",
    "btn_war.png",
    "btn_join.png",
    "btn_new_troop.png",
    "btn_march.png",
    "btn_notice_no.png",
    "icon_march_active.png",
    "march_full.png",
    "btn_return.png",
    "ap_status_label.png",
    "ap_plus.png",
    "ap_claim.png",
    "ap_use.png",
    "ap_modal_close.png",
    "ap_profile_close.png",
    "troop_type_infantry.png",
    "troop_type_archer.png",
    "troop_type_cavalry.png",
    "troop_slots.png",
]

TROOP_TYPE_TEMPLATES = {
    "infantry": "troop_type_infantry.png",
    "archer": "troop_type_archer.png",
    "cavalry": "troop_type_cavalry.png",
}
TROOP_TYPE_SLOTS = {
    "cavalry": (1, 2),
    "infantry": (3, 4),
    "archer": (5,),
}
TROOP_TYPE_LABELS = {
    "cavalry": "kỵ",
    "infantry": "bộ",
    "archer": "cung",
}
TROOP_SLOT_X_RATIO = 16 / 41
TROOP_SLOT_Y_RATIOS = (
    14 / 228,
    54 / 228,
    90 / 228,
    130 / 228,
    166 / 228,
    206 / 228,
)

scale_cache = {}
gui_root = None
gui_status_var = None


def log(msg):
  formatted = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
  print(formatted)
  if gui_root is not None and gui_status_var is not None:
    short_msg = msg if len(msg) <= 42 else msg[:39] + "..."
    try:
      gui_root.after(0, lambda m=short_msg: gui_status_var.set(m))
    except Exception:
      pass


def stop_bot_now(reason="Người dùng bấm nút tắt"):
  print(f"[{datetime.now().strftime('%H:%M:%S')}] {reason} -> Đã tắt bot!")
  try:
    if gui_root is not None:
      gui_root.destroy()
  except Exception:
    pass
  os._exit(0)


def check_stop_hotkey():
  """Nhấn phím F12 bất cứ lúc nào để dừng bot ngay lập tức."""
  if ctypes.windll.user32.GetAsyncKeyState(0x7B) & 0x8000:
    stop_bot_now("Đã nhận phím tắt F12")


def smart_sleep(seconds):
  """Ngủ theo từng nhịp ngắn 0.1s để phím tắt F12 có thể ngắt bot tức thì."""
  end_time = time.time() + seconds
  while time.time() < end_time:
    check_stop_hotkey()
    remaining = end_time - time.time()
    if remaining > 0:
      time.sleep(min(0.1, remaining))


def is_admin():
  try:
    return ctypes.windll.shell32.IsUserAnAdmin()
  except Exception:
    return False


def check_templates():
  missing = [f for f in REQUIRED_TEMPLATES if not os.path.exists(f)]
  if missing:
    print(f"LỖI: Thiếu file ảnh mẫu trong thư mục ROKBOT2: {', '.join(missing)}")
    return False
  if not os.path.isfile(TESSERACT_PATH):
    print(
        "LỖI: Không tìm thấy Tesseract OCR; cần cài Tesseract để đọc khoảng"
        " cách rally."
    )
    return False
  return True


def get_all_rok_hwnds():
  hwnds = []

  def enum_callback(hwnd, _):
    if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
      return
    title = win32gui.GetWindowText(hwnd)
    if "Rise of Kingdoms" in title:
      rect = win32gui.GetClientRect(hwnd)
      if (rect[2] - rect[0]) > 200 and (rect[3] - rect[1]) > 200:
        hwnds.append(hwnd)

  win32gui.EnumWindows(enum_callback, None)
  hwnds.sort()
  return hwnds


def get_window_rect(hwnd):
  if not win32gui.IsWindow(hwnd) or win32gui.IsIconic(hwnd):
    return None
  rect = win32gui.GetClientRect(hwnd)
  left, top = win32gui.ClientToScreen(hwnd, (0, 0))
  width = rect[2] - rect[0]
  height = rect[3] - rect[1]
  if width <= 200 or height <= 200:
    return None
  return {
      "hwnd": hwnd,
      "left": left,
      "top": top,
      "width": width,
      "height": height,
  }


def arrange_staircase(hwnds):
  """Xếp gọn các cửa sổ thành bậc thang mà không thay đổi kích thước khung game."""
  start_x, start_y = 50, 35
  step_x, step_y = 65, 40
  for i, hwnd in enumerate(hwnds):
    x = start_x + i * step_x
    y = start_y + i * step_y
    win32gui.SetWindowPos(
        hwnd,
        win32con.HWND_TOP,
        x,
        y,
        0,
        0,
        win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
    )
    smart_sleep(0.08)


def focus_window(hwnd):
  """Đưa cửa sổ cần quét lên lớp trên cùng để chụp ảnh và click chính xác."""
  try:
    if win32gui.GetForegroundWindow() != hwnd:
      win32gui.SetWindowPos(
          hwnd,
          win32con.HWND_TOP,
          0,
          0,
          0,
          0,
          win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
      )
      ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
      ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
      win32gui.SetForegroundWindow(hwnd)
      smart_sleep(0.35)
    return win32gui.GetForegroundWindow() == hwnd
  except Exception:
    return False


def grab_window(sct, hwnd):
  win = get_window_rect(hwnd)
  if not win:
    return None, None
  screenshot = np.array(sct.grab(win))
  screen_bgr = cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)
  return win, screen_bgr


def match_multiscale(screen_img, template, cache_key, threshold):
  orig_h, orig_w = template.shape[:2]
  scales_to_try = (
      [scale_cache[cache_key]]
      if cache_key in scale_cache
      else np.linspace(0.35, 1.60, 26)
  )

  best_val = -1
  best_loc = None
  best_size = (orig_w, orig_h)
  best_scale = 1.0

  for scale in scales_to_try:
    new_w = int(orig_w * scale)
    new_h = int(orig_h * scale)
    if (
        new_w < 8
        or new_h < 8
        or new_w >= screen_img.shape[1]
        or new_h >= screen_img.shape[0]
    ):
      continue

    resized = cv2.resize(
        template, (new_w, new_h), interpolation=cv2.INTER_AREA
    )
    res = cv2.matchTemplate(screen_img, resized, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)

    if max_val > best_val:
      best_val = max_val
      best_loc = max_loc
      best_size = (new_w, new_h)
      best_scale = scale

  if best_val < threshold and cache_key in scale_cache:
    del scale_cache[cache_key]
    return None, None

  if best_val >= threshold and best_loc is not None:
    scale_cache[cache_key] = best_scale
    center = (best_loc[0] + best_size[0] // 2, best_loc[1] + best_size[1] // 2)
    return center, best_size

  return None, None


def find_template(
    sct, hwnd, template_path, threshold=0.80, roi_ratio=None, use_gray=False
):
  win, screen_bgr = grab_window(sct, hwnd)
  if win is None:
    return None, None, None

  offset_x, offset_y = 0, 0
  search_img = screen_bgr
  if roi_ratio is not None:
    h, w = screen_bgr.shape[:2]
    x1, y1 = int(w * roi_ratio[0]), int(h * roi_ratio[1])
    x2, y2 = int(w * roi_ratio[2]), int(h * roi_ratio[3])
    search_img = screen_bgr[y1:y2, x1:x2]
    offset_x, offset_y = x1, y1

  if use_gray:
    template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
    search_img = cv2.cvtColor(search_img, cv2.COLOR_BGR2GRAY)
  else:
    template = cv2.imread(template_path, cv2.IMREAD_COLOR)

  if template is None:
    return None, None, None

  cache_key = (hwnd, win["width"], template_path, use_gray)
  pos, size = match_multiscale(search_img, template, cache_key, threshold)
  if pos:
    full_pos = (pos[0] + offset_x, pos[1] + offset_y)
    return win, full_pos, size
  return win, None, None


def click_window_position(win, pos):
  target_x = win["left"] + pos[0] + random.randint(-3, 3)
  target_y = win["top"] + pos[1] + random.randint(-3, 3)
  pyautogui.moveTo(target_x, target_y, duration=random.uniform(0.08, 0.16))
  pyautogui.click()


def find_and_click(sct, hwnd, template_path, threshold=0.80, roi_ratio=None):
  return (
      find_and_click_with_position(
          sct, hwnd, template_path, threshold=threshold, roi_ratio=roi_ratio
      )
      is not None
  )


def find_and_click_with_position(
    sct, hwnd, template_path, threshold=0.80, roi_ratio=None
):
  win, pos, _ = find_template(sct, hwnd, template_path, threshold, roi_ratio)
  if win is None or pos is None:
    return None

  click_window_position(win, pos)
  return pos


def find_template_positions(sct, hwnd, template_path, threshold=0.80):
  win, _, size = find_template(sct, hwnd, template_path, threshold)
  if win is None or size is None:
    return None, [], None

  win, screen_bgr = grab_window(sct, hwnd)
  template = cv2.imread(template_path, cv2.IMREAD_COLOR)
  if win is None or screen_bgr is None or template is None:
    return None, [], None

  resized = cv2.resize(
      template, size, interpolation=cv2.INTER_AREA
  )
  result = cv2.matchTemplate(
      screen_bgr, resized, cv2.TM_CCOEFF_NORMED
  )
  template_h, template_w = resized.shape[:2]
  positions = []

  for _ in range(20):
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
      break

    x, y = max_loc
    positions.append(
        (x + template_w // 2, y + template_h // 2)
    )
    x1 = max(0, x - template_w // 2)
    y1 = max(0, y - template_h // 2)
    x2 = min(result.shape[1] - 1, x + template_w + template_w // 2)
    y2 = min(result.shape[0] - 1, y + template_h + template_h // 2)
    cv2.rectangle(result, (x1, y1), (x2, y2), -1, thickness=-1)

  return win, positions, size


def is_green_joinable_rally(screen_bgr, join_pos, join_size):
  if screen_bgr is None or join_size is None:
    return False

  height, width = screen_bgr.shape[:2]
  join_x, join_y = join_pos
  button_w, button_h = join_size

  button_x1 = max(0, join_x - button_w // 2)
  button_y1 = max(0, join_y - button_h // 2)
  button_x2 = min(width, button_x1 + button_w)
  button_y2 = min(height, button_y1 + button_h)
  if button_x2 <= button_x1 or button_y2 <= button_y1:
    return False

  button_hsv = cv2.cvtColor(
      screen_bgr[button_y1:button_y2, button_x1:button_x2], cv2.COLOR_BGR2HSV
  )
  green_button = cv2.inRange(
      button_hsv, np.array([38, 100, 70]), np.array([90, 255, 255])
  )
  if np.count_nonzero(green_button) / green_button.size < 0.30:
    return False

  bar_x1 = max(0, join_x - int(button_w * 18.8))
  bar_x2 = min(width, join_x - int(button_w * 1.6))
  bar_y1 = max(0, join_y - int(button_h * 0.43))
  bar_y2 = min(height, join_y + int(button_h * 0.52))
  if bar_x2 <= bar_x1 or bar_y2 <= bar_y1:
    return False

  bar_hsv = cv2.cvtColor(
      screen_bgr[bar_y1:bar_y2, bar_x1:bar_x2], cv2.COLOR_BGR2HSV
  )
  red_status = cv2.inRange(
      bar_hsv, np.array([0, 100, 70]), np.array([10, 255, 255])
  ) | cv2.inRange(
      bar_hsv, np.array([170, 100, 70]), np.array([179, 255, 255])
  )
  yellow_status = cv2.inRange(
      bar_hsv, np.array([18, 100, 70]), np.array([35, 255, 255])
  )
  total_pixels = bar_hsv.shape[0] * bar_hsv.shape[1]
  return (
      np.count_nonzero(red_status) / total_pixels < 0.10
      and np.count_nonzero(yellow_status) / total_pixels < 0.10
  )


def read_rally_distance_km(screen_bgr, join_pos, join_size):
  if screen_bgr is None or join_size is None:
    return None

  height, width = screen_bgr.shape[:2]
  join_x, join_y = join_pos
  button_w, button_h = join_size
  x1 = max(0, join_x - int(button_w * 29))
  x2 = min(width, join_x - int(button_w * 23.5))
  y1 = max(0, join_y - int(button_h * 4))
  y2 = min(height, join_y - int(button_h * 2.8))
  if x2 <= x1 or y2 <= y1:
    return None

  badge = screen_bgr[y1:y2, x1:x2]
  distance_badge = cv2.resize(
      badge,
      None,
      fx=4,
      fy=4,
      interpolation=cv2.INTER_CUBIC,
  )
  gray_badge = cv2.cvtColor(badge, cv2.COLOR_BGR2GRAY)
  threshold_badge = cv2.threshold(
      gray_badge, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
  )[1]
  threshold_badge = cv2.resize(
      threshold_badge,
      None,
      fx=4,
      fy=4,
      interpolation=cv2.INTER_CUBIC,
  )

  def recognize_distance(image, page_segmentation_mode):
    text = pytesseract.image_to_string(
        image,
        config=(
            f"--psm {page_segmentation_mode} "
            "-c tessedit_char_whitelist=0123456789KM"
        ),
    )
    normalized_text = "".join(text.upper().split())
    match = re.fullmatch(r"(\d{1,3})KM", normalized_text)
    return int(match.group(1)) if match else None

  readings = [
      recognize_distance(distance_badge, 8),
      recognize_distance(distance_badge, 13),
      recognize_distance(threshold_badge, 8),
  ]
  for distance_km in readings:
    if distance_km is not None and readings.count(distance_km) >= 2:
      return distance_km
  return None


def find_joinable_rally(sct, hwnd):
  win, positions, join_size = find_template_positions(
      sct, hwnd, "btn_join.png", threshold=0.80
  )
  if win is None or join_size is None or not positions:
    return None, None

  win, screen_bgr = grab_window(sct, hwnd)
  if win is None or screen_bgr is None:
    return None, None

  for join_pos in sorted(positions, key=lambda pos: pos[1]):
    if is_green_joinable_rally(screen_bgr, join_pos, join_size):
      distance_km = read_rally_distance_km(
          screen_bgr, join_pos, join_size
      )
      if distance_km is None:
        log("Không đọc rõ khoảng cách rally; bỏ qua để tránh tham gia quá xa.")
        continue
      if distance_km > MAX_RALLY_DISTANCE_KM:
        log(
            f"Rally cách {distance_km} km, vượt quá"
            f" {MAX_RALLY_DISTANCE_KM} km; bỏ qua."
        )
        continue
      return win, join_pos
  return None, None


def find_rally_troop_type(sct, hwnd, rally_y):
  _, screen_bgr = grab_window(sct, hwnd)
  if screen_bgr is None:
    return None

  matches = []
  for troop_type, template_path in TROOP_TYPE_TEMPLATES.items():
    _, panel_positions, panel_size = find_template_positions(
        sct, hwnd, template_path, threshold=0.80
    )
    if not panel_positions or panel_size is None:
      continue

    for panel_pos in sorted(
        panel_positions, key=lambda pos: abs(pos[1] - rally_y)
    ):
      distance = abs(panel_pos[1] - rally_y)
      if distance > panel_size[1]:
        break

      panel_x = panel_pos[0] - panel_size[0] // 2
      panel_y = panel_pos[1] - panel_size[1] // 2
      panel = screen_bgr[
          panel_y : panel_y + panel_size[1],
          panel_x : panel_x + panel_size[0],
      ]
      if panel.shape[:2] != (panel_size[1], panel_size[0]):
        continue

      detected_type = classify_troop_type_icon(panel)
      if detected_type == troop_type:
        matches.append((distance, troop_type, panel_size[1]))
        break

  if not matches:
    return None

  matches.sort(key=lambda match: match[0])
  if (
      len(matches) > 1
      and abs(matches[0][0] - matches[1][0]) <= max(2, matches[0][2] * 0.1)
  ):
    return None

  return matches[0][1]


def classify_troop_type_icon(panel):
  hsv = cv2.cvtColor(panel, cv2.COLOR_BGR2HSV)
  red_mask = cv2.inRange(
      hsv, np.array([0, 100, 60]), np.array([10, 255, 255])
  ) | cv2.inRange(
      hsv, np.array([170, 100, 60]), np.array([179, 255, 255])
  )

  h, w = red_mask.shape
  half_w, half_h = w // 2, h // 2
  icon_regions = (
      (0, 0, half_w, half_h),
      (half_w, 0, w, half_h),
      (0, half_h, half_w, h),
      (half_w, half_h, w, h),
  )
  red_counts = [
      np.count_nonzero(red_mask[y1:y2, x1:x2])
      for x1, y1, x2, y2 in icon_regions
  ]

  selected_icon = int(np.argmax(red_counts))
  if red_counts[selected_icon] < max(4, int(h * w * 0.035)):
    return None

  return {
      0: "infantry",
      1: "cavalry",
      2: "archer",
  }.get(selected_icon)


def select_troop_slots(sct, hwnd, slot_numbers):
  if any(
      not 1 <= slot_number <= len(TROOP_SLOT_Y_RATIOS)
      for slot_number in slot_numbers
  ):
    raise ValueError(f"Invalid troop slot numbers: {slot_numbers}")

  win, panel_pos, panel_size = find_template(
      sct, hwnd, "troop_slots.png", threshold=0.65
  )
  if win is None or panel_pos is None or panel_size is None:
    return False

  panel_x = panel_pos[0] - panel_size[0] // 2
  panel_y = panel_pos[1] - panel_size[1] // 2
  slot_positions = [
      (
          panel_x + int(panel_size[0] * TROOP_SLOT_X_RATIO),
          panel_y + int(panel_size[1] * TROOP_SLOT_Y_RATIOS[slot_number - 1]),
      )
      for slot_number in slot_numbers
  ]
  for slot_pos in slot_positions:
    click_window_position(win, slot_pos)

  return True


def read_ap_fill_ratio(sct, hwnd, is_modal=False):
  template_path = "ap_modal_close.png" if is_modal else "ap_status_label.png"
  roi_ratio = AP_MODAL_CLOSE_ROI if is_modal else None
  win, anchor_pos, anchor_size = find_template(
      sct, hwnd, template_path, threshold=0.76, roi_ratio=roi_ratio
  )
  if win is None or anchor_pos is None or anchor_size is None:
    return None

  template = cv2.imread(template_path, cv2.IMREAD_COLOR)
  if template is None:
    return None

  scale = anchor_size[0] / template.shape[1]
  origin_x = anchor_pos[0] - anchor_size[0] // 2
  origin_y = anchor_pos[1] - anchor_size[1] // 2

  if is_modal:
    x1 = origin_x - int(446 * scale)
    x2 = origin_x - int(144 * scale)
    y1 = origin_y + int(49 * scale)
    y2 = origin_y + int(67 * scale)
  else:
    x1 = origin_x + int(18 * scale)
    x2 = origin_x + int(306 * scale)
    y1 = origin_y + int(19 * scale)
    y2 = origin_y + int(26 * scale)

  win, screen_bgr = grab_window(sct, hwnd)
  if win is None or screen_bgr is None:
    return None

  x1 = max(0, x1)
  x2 = min(screen_bgr.shape[1], x2)
  y1 = max(0, y1)
  y2 = min(screen_bgr.shape[0], y2)
  if x2 <= x1 or y2 <= y1:
    return None

  bar = screen_bgr[y1:y2, x1:x2]
  hsv = cv2.cvtColor(bar, cv2.COLOR_BGR2HSV)
  fill_mask = cv2.inRange(
      hsv, np.array([18, 100, 70]), np.array([95, 255, 255])
  )
  filled_columns = np.count_nonzero(fill_mask, axis=0) >= max(
      1, bar.shape[0] // 3
  )
  filled_indices = np.flatnonzero(filled_columns)
  if not len(filled_indices):
    return 0.0
  return (filled_indices[-1] + 1) / len(filled_columns)


def close_ap_windows(sct, hwnd, template_paths):
  for template_path in template_paths:
    if template_path == "ap_modal_close.png":
      roi_ratio = AP_MODAL_CLOSE_ROI
    elif template_path == "ap_profile_close.png":
      roi_ratio = AP_PROFILE_CLOSE_ROI
    else:
      roi_ratio = None
    if not find_and_click(
        sct,
        hwnd,
        template_path,
        threshold=0.76,
        roi_ratio=roi_ratio,
    ):
      log(f"Không tìm thấy nút đóng {template_path}.")
      return False
    smart_sleep(random.uniform(0.45, 0.7))
  return True


def click_avatar_for_ap_check(hwnd):
  win = get_window_rect(hwnd)
  if win is None:
    return False

  click_window_position(
      win,
      (
          int(win["width"] * AP_AVATAR_CLICK_RATIO[0]),
          int(win["height"] * AP_AVATAR_CLICK_RATIO[1]),
      ),
  )
  return True


def close_ap_profile_and_verify(sct, hwnd, modal_open=False):
  template_paths = (
      ["ap_modal_close.png", "ap_profile_close.png"]
      if modal_open
      else ["ap_profile_close.png"]
  )
  if not close_ap_windows(sct, hwnd, template_paths):
    return False
  if read_ap_fill_ratio(sct, hwnd) is not None:
    log("Bảng AP vẫn đang mở; hoãn vào Alliance/War lượt này.")
    return False
  return True


def refill_action_points(sct, hwnd):
  ap_ratio = read_ap_fill_ratio(sct, hwnd)
  if ap_ratio is None:
    if not click_avatar_for_ap_check(hwnd):
      log("Không xác định được cửa sổ để mở thanh AP.")
      return False
    smart_sleep(random.uniform(0.5, 0.8))
    ap_ratio = read_ap_fill_ratio(sct, hwnd)

  if ap_ratio is None:
    log("Không đọc được thanh AP; bỏ qua nạp AP.")
    return close_ap_profile_and_verify(sct, hwnd)

  if ap_ratio >= AP_LOW_THRESHOLD:
    return close_ap_profile_and_verify(sct, hwnd)

  log(f"AP còn khoảng {ap_ratio:.0%}; bắt đầu nạp AP.")
  if not find_and_click(sct, hwnd, "ap_plus.png", threshold=0.76):
    log("Không tìm thấy dấu cộng AP; bỏ qua nạp AP.")
    return close_ap_profile_and_verify(sct, hwnd)
  smart_sleep(random.uniform(0.5, 0.8))

  ap_ratio = read_ap_fill_ratio(sct, hwnd, is_modal=True)
  if ap_ratio is None:
    log("Không đọc được thanh AP trong cửa sổ nạp.")
    return close_ap_profile_and_verify(sct, hwnd, modal_open=True)

  if find_and_click(sct, hwnd, "ap_claim.png", threshold=0.78):
    log("Đã nhận Daily Action Point Recovery.")
    smart_sleep(random.uniform(0.6, 0.9))

  win = get_window_rect(hwnd)
  if win is not None:
    pyautogui.moveTo(
        win["left"] + win["width"] // 2,
        win["top"] + int(win["height"] * 0.68),
        duration=random.uniform(0.08, 0.14),
    )
    pyautogui.scroll(-12)
    smart_sleep(0.5)

  for _ in range(MAX_AP_USE_CLICKS):
    ap_ratio = read_ap_fill_ratio(sct, hwnd, is_modal=True)
    if ap_ratio is None:
      log("Mất thanh AP trong lúc dùng vật phẩm; dừng nạp.")
      break
    if ap_ratio >= AP_FULL_THRESHOLD:
      log("Thanh AP đã đầy.")
      break

    use_win, use_positions, _ = find_template_positions(
        sct, hwnd, "ap_use.png", threshold=0.80
    )
    if use_win is None or not use_positions:
      log("Không còn thấy nút USE; dừng nạp AP.")
      break

    use_pos = max(use_positions, key=lambda pos: pos[1])
    click_window_position(use_win, use_pos)
    smart_sleep(random.uniform(0.7, 1.0))

    updated_ratio = read_ap_fill_ratio(sct, hwnd, is_modal=True)
    if updated_ratio is None or updated_ratio <= ap_ratio:
      log("AP không tăng sau khi bấm USE; dừng để tránh bấm lặp.")
      break

  return close_ap_profile_and_verify(sct, hwnd, modal_open=True)


def scroll_war_list(hwnd):
  win = get_window_rect(hwnd)
  if win is None:
    return False

  x = win["left"] + win["width"] // 2
  y = win["top"] + int(win["height"] * 0.40)
  pyautogui.moveTo(x, y, duration=random.uniform(0.08, 0.14))
  pyautogui.scroll(-1)
  smart_sleep(
      random.uniform(RALLY_SCROLL_SETTLE_MIN, RALLY_SCROLL_SETTLE_MAX)
  )
  return True


def ensure_world_map(sct, hwnd):
  """Đảm bảo tab trở về đúng màn hình Bản đồ ngoài thành (nút Lâu đài xanh dương ở góc dưới phải)."""
  bottom_right_roi = (0.85, 0.80, 1.0, 1.0)

  for _ in range(6):
    _, world_pos, _ = find_template(
        sct,
        hwnd,
        "icon_world_map.png",
        threshold=0.78,
        roi_ratio=bottom_right_roi,
    )
    if world_pos is not None:
      return True

    if find_and_click(
        sct,
        hwnd,
        "btn_to_map.png",
        threshold=0.78,
        roi_ratio=bottom_right_roi,
    ):
      smart_sleep(1.1)
      continue

    pyautogui.press("esc")
    smart_sleep(0.45)

  return False


def is_five_marches_out(
    sct, hwnd, screen_bgr, active_pos, active_size, top_right_roi
):
  """Kiểm tra đã đủ 5/5 đạo quân ra ngoài chưa bằng 2 lớp:

  1. Nhận diện ảnh xám dòng chữ '5/5' (tránh nhiễu màu nền bản đồ).
  2. Đếm số huy hiệu trạng thái (xanh lá/xanh dương) của 5 ô tướng F1-F5.
  """
  # Lớp 1: So khớp ảnh xám '5/5'
  _, full_pos, _ = find_template(
      sct,
      hwnd,
      "march_full.png",
      threshold=0.70,
      roi_ratio=top_right_roi,
      use_gray=True,
  )
  if full_pos is not None:
    return True

  # Lớp 2: Đếm số huy hiệu trạng thái tròn ở góc dưới bên phải từng ô tướng
  if active_pos is None or active_size is None or screen_bgr is None:
    return False

  ix, iy = active_pos
  iw, ih = active_size
  h, w = screen_bgr.shape[:2]

  x1 = max(0, ix + int(iw * 1.60))
  x2 = min(w, ix + int(iw * 3.10))
  y1 = max(0, iy + int(ih * 0.80))
  y2 = min(h, iy + int(ih * 15.0))

  if x2 <= x1 or y2 <= y1:
    return False

  badge_strip = screen_bgr[y1:y2, x1:x2]
  hsv = cv2.cvtColor(badge_strip, cv2.COLOR_BGR2HSV)

  # Huy hiệu tròn màu xanh lá (thu thập/di chuyển) và xanh dương (cờ/rally)
  green_mask = cv2.inRange(
      hsv, np.array([38, 130, 120]), np.array([85, 255, 255])
  )
  blue_mask = cv2.inRange(
      hsv, np.array([92, 130, 120]), np.array([125, 255, 255])
  )
  combined_mask = cv2.bitwise_or(green_mask, blue_mask)

  contours, _ = cv2.findContours(
      combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
  )
  min_badge_d = max(5, int(ih * 0.28))
  max_badge_d = max(14, int(ih * 0.95))

  badge_ys = []
  for cnt in contours:
    _, by, bw, bh = cv2.boundingRect(cnt)
    if min_badge_d <= bw <= max_badge_d and min_badge_d <= bh <= max_badge_d:
      center_y = by + bh // 2
      if all(abs(center_y - prev_y) > int(ih * 1.1) for prev_y in badge_ys):
        badge_ys.append(center_y)

  return len(badge_ys) >= 5


def find_yellow_health_portrait(screen_bgr, active_icon_pos, active_icon_size):
  """Dò vạch máu dọc màu vàng sát mép phải ô tướng (F1-F5)."""
  ix, iy = active_icon_pos
  iw, ih = active_icon_size
  h, w = screen_bgr.shape[:2]

  x1 = max(0, ix + int(iw * 2.20))
  x2 = min(w, ix + int(iw * 3.80))
  y1 = max(0, iy + int(ih * 0.50))
  y2 = min(h, iy + int(ih * 18.0))

  if x2 <= x1 or y2 <= y1:
    return None

  bar_strip = screen_bgr[y1:y2, x1:x2]
  hsv = cv2.cvtColor(bar_strip, cv2.COLOR_BGR2HSV)

  yellow_mask = cv2.inRange(
      hsv, np.array([20, 145, 165]), np.array([35, 255, 255])
  )
  contours, _ = cv2.findContours(
      yellow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
  )

  for cnt in contours:
    bx, by, bw, bh = cv2.boundingRect(cnt)
    if bh >= max(8, int(ih * 0.35)) and bh > bw:
      bar_center_y = y1 + by + bh // 2
      portrait_center_x = ix + int(iw * 1.50)
      return (portrait_center_x, bar_center_y)

  return None


def recall_yellow_march(sct, hwnd, win, portrait_pos):
  """Bấm chọn ô tướng bị vàng máu và bấm nút Return để rút quân về hẳn thành."""
  px = win["left"] + portrait_pos[0] + random.randint(-3, 3)
  py = win["top"] + portrait_pos[1] + random.randint(-3, 3)
  pyautogui.moveTo(px, py, duration=random.uniform(0.08, 0.16))
  pyautogui.click()
  smart_sleep(random.uniform(0.6, 0.9))

  return find_and_click(sct, hwnd, "btn_return.png", threshold=0.78)


def open_alliance_and_war(sct, hwnd):
  """Đảm bảo đang ở Bản đồ ngoài thành rồi mới bấm Alliance -> War."""
  if not ensure_world_map(sct, hwnd):
    return False

  if find_and_click(sct, hwnd, "btn_alliance.png", threshold=0.80):
    smart_sleep(random.uniform(0.7, 1.0))
    if find_and_click(sct, hwnd, "btn_war.png", threshold=0.80):
      smart_sleep(random.uniform(0.7, 1.0))
      return True
  return False


def bot_worker():
  hwnds = get_all_rok_hwnds()
  if not hwnds:
    log("Không tìm thấy cửa sổ Rise of Kingdoms nào đang mở!")
    return

  log(f"Đã nhận diện {len(hwnds)} cửa sổ Rise of Kingdoms.")
  if AUTO_CASCADE:
    arrange_staircase(hwnds)
    log("Đã xếp xong các tab theo dạng bậc thang.")

  next_scan = {}
  full_queue_pause_until = {}
  waiting_heal = {}
  top_right_roi = (0.80, 0.05, 1.0, 0.45)

  def schedule_next_scan(hwnd, wait_sec):
    next_time = time.time() + wait_sec
    pause_until = full_queue_pause_until.get(hwnd)
    if pause_until is not None and pause_until > time.time():
      next_time = min(next_time, pause_until)
    next_scan[hwnd] = next_time

  log(
      f"Bắt đầu chạy: chu kỳ {SCAN_MIN}s - {SCAN_MAX}s/tab về Bản đồ -> Alliance"
      " -> War, tham gia các rally có thể."
  )
  print("-" * 60)

  with mss.mss() as sct:
    while True:
      check_stop_hotkey()
      hwnds = get_all_rok_hwnds()
      if not hwnds:
        smart_sleep(3)
        continue

      active_set = set(hwnds)
      for old_hwnd in list(next_scan.keys()):
        if old_hwnd not in active_set:
          del next_scan[old_hwnd]
          full_queue_pause_until.pop(old_hwnd, None)
          waiting_heal.pop(old_hwnd, None)

      now = time.time()
      for idx, hwnd in enumerate(hwnds, start=1):
        check_stop_hotkey()
        if now < next_scan.get(hwnd, 0):
          continue

        if not focus_window(hwnd):
          log(f"[Bậc {idx}] Không thể đưa cửa sổ game lên trước; bỏ qua lượt.")
          schedule_next_scan(hwnd, 3)
          continue

        wait_sec = random.uniform(SCAN_MIN, SCAN_MAX)

        # BƯỚC TIÊN QUYẾT: Trở về đúng màn hình Bản đồ ngoài thành
        if not ensure_world_map(sct, hwnd):
          log(
              f"[Bậc {idx}] Chưa về được Bản đồ ngoài thành. Thử lại sau"
              f" {wait_sec:.0f}s."
          )
          schedule_next_scan(hwnd, wait_sec)
          smart_sleep(random.uniform(1.0, 1.5))
          continue

        win, active_pos, active_size = find_template(
            sct,
            hwnd,
            "icon_march_active.png",
            threshold=0.78,
            roi_ratio=top_right_roi,
        )
        _, screen_bgr = grab_window(sct, hwnd)

        # 1. KIỂM TRA QUÂN VÀNG MÁU -> Cho về hẳn thành & bỏ qua check Alliance
        if (
            active_pos is not None
            and win is not None
            and screen_bgr is not None
        ):
          yellow_portrait = find_yellow_health_portrait(
              screen_bgr, active_pos, active_size
          )
          if yellow_portrait is not None:
            waiting_heal[hwnd] = True
            recalled = recall_yellow_march(sct, hwnd, win, yellow_portrait)
            if recalled:
              log(
                  f"[Bậc {idx}] Quân vàng máu! Đã rút về thành & dừng check"
                  f" Alliance ({wait_sec:.0f}s)."
              )
            else:
              log(
                  f"[Bậc {idx}] Quân vàng máu! Dừng check Alliance & đang rút"
                  f" về ({wait_sec:.0f}s)."
              )
            schedule_next_scan(hwnd, wait_sec)
            smart_sleep(random.uniform(1.0, 1.5))
            continue

        if waiting_heal.get(hwnd, False):
          waiting_heal[hwnd] = False
          log(f"[Bậc {idx}] Quân vàng máu đã về thành.")

        pause_until = full_queue_pause_until.get(hwnd)
        if pause_until is not None and time.time() < pause_until:
          remaining = pause_until - time.time()
          log(
              f"[Bậc {idx}] Đang nghỉ sau khi đầy 5/5; bỏ qua Alliance"
              f" thêm {remaining:.0f}s."
          )
          schedule_next_scan(hwnd, wait_sec)
          smart_sleep(random.uniform(1.0, 1.5))
          continue
        full_queue_pause_until.pop(hwnd, None)

        # 2. HÀNG CHỜ ĐỦ 5/5 -> Tạm ngưng check rally ngẫu nhiên 2-5 phút
        if is_five_marches_out(
            sct, hwnd, screen_bgr, active_pos, active_size, top_right_roi
        ):
          pause_sec = random.uniform(
              FULL_QUEUE_PAUSE_MIN, FULL_QUEUE_PAUSE_MAX
          )
          full_queue_pause_until[hwnd] = time.time() + pause_sec
          log(
              f"[Bậc {idx}] Hàng chờ đủ 5/5! Tạm ngưng check Alliance"
              f" trong {pause_sec / 60:.1f} phút."
          )
          schedule_next_scan(hwnd, wait_sec)
          smart_sleep(random.uniform(1.0, 1.5))
          continue

        # 3. NẠP AP NẾU DƯỚI 25%, SAU ĐÓ VÀO ALLIANCE -> WAR
        if not refill_action_points(sct, hwnd):
          log(
              f"[Bậc {idx}] Chưa xác nhận đóng hồ sơ AP; bỏ qua Alliance/War"
              " lượt này."
          )
          schedule_next_scan(hwnd, wait_sec)
          smart_sleep(random.uniform(1.0, 1.5))
          continue
        log(f"[Bậc {idx}] Đang vào Alliance -> War...")
        if open_alliance_and_war(sct, hwnd):
          joined_rallies = 0
          scroll_count = 0
          skip_after_rejected_rally = False
          rejected_join_pos = None
          queue_full = False
          no_new_rally_found = False

          while joined_rallies < MAX_RALLIES_PER_SCAN:
            check_stop_hotkey()
            _, world_pos, _ = find_template(
                sct,
                hwnd,
                "icon_world_map.png",
                threshold=0.78,
                roi_ratio=(0.85, 0.80, 1.0, 1.0),
            )
            if world_pos is not None:
              if not open_alliance_and_war(sct, hwnd):
                log(f"[Bậc {idx}] Không thể mở lại Alliance -> War.")
                break

            if skip_after_rejected_rally:
              if scroll_count >= MAX_WAR_LIST_SCROLLS:
                no_new_rally_found = True
                break
              if not scroll_war_list(hwnd):
                break
              scroll_count += 1
              _, next_join_pos, _ = find_template(
                  sct, hwnd, "btn_join.png", threshold=0.80
              )
              if next_join_pos != rejected_join_pos:
                skip_after_rejected_rally = False
              continue

            join_win, join_pos = find_joinable_rally(sct, hwnd)
            if join_pos is None:
              if scroll_count >= MAX_WAR_LIST_SCROLLS:
                no_new_rally_found = True
                log(
                    f"[Bậc {idx}] Đã cuộn {scroll_count} lần, không tìm thấy"
                    " thêm rally có nút Join xanh và trạng thái phù hợp."
                )
                break
              if not scroll_war_list(hwnd):
                break
              scroll_count += 1
              continue

            troop_type = find_rally_troop_type(sct, hwnd, join_pos[1])
            if troop_type not in TROOP_TYPE_SLOTS:
              log(
                  f"[Bậc {idx}] Không nhận diện được loại quân rally; "
                  "bỏ qua để tránh chọn sai đội hình."
              )
              rejected_join_pos = join_pos
              skip_after_rejected_rally = True
              continue

            troop_slots = TROOP_TYPE_SLOTS[troop_type]
            log(
                f"[Bậc {idx}] Rally {TROOP_TYPE_LABELS[troop_type]}; "
                f"chọn ô quân {', '.join(map(str, troop_slots))}."
            )
            click_window_position(join_win, join_pos)
            log(f"[Bậc {idx}] Có rally có thể tham gia! Bấm New Troop...")
            smart_sleep(random.uniform(0.7, 1.0))
            if not find_and_click(
                sct, hwnd, "btn_new_troop.png", threshold=0.78
            ):
              log(f"[Bậc {idx}] Không thấy New Troop; dừng lượt dò rally.")
              ensure_world_map(sct, hwnd)
              break

            smart_sleep(random.uniform(0.6, 0.9))
            if not select_troop_slots(sct, hwnd, troop_slots):
              log(
                  f"[Bậc {idx}] Không nhận diện được danh sách ô quân; "
                  "hủy lượt để tránh gửi sai đội hình."
              )
              ensure_world_map(sct, hwnd)
              break

            if not find_and_click(sct, hwnd, "btn_march.png", threshold=0.78):
              log(
                  f"[Bậc {idx}] Không thấy MARCH (có thể hết AP hoặc hàng"
                  " chờ); dừng lượt dò rally."
              )
              ensure_world_map(sct, hwnd)
              break

            smart_sleep(random.uniform(0.6, 0.9))
            if find_and_click(
                sct, hwnd, "btn_notice_no.png", threshold=0.80
            ):
              log(
                  f"[Bậc {idx}] Rally quá xa (NOTICE); bấm NO và bỏ qua rally"
                  " này để thử các rally khác."
              )
              rejected_join_pos = join_pos
              skip_after_rejected_rally = True
              smart_sleep(random.uniform(0.5, 0.8))
              continue

            joined_rallies += 1
            log(
                f"[Bậc {idx}] Đã tham gia rally {joined_rallies}; tiếp tục"
                " tìm rally khác."
            )

            win, active_pos, active_size = find_template(
                sct,
                hwnd,
                "icon_march_active.png",
                threshold=0.78,
                roi_ratio=top_right_roi,
            )
            _, screen_bgr = grab_window(sct, hwnd)
            if is_five_marches_out(
                sct,
                hwnd,
                screen_bgr,
                active_pos,
                active_size,
                top_right_roi,
            ):
              pause_sec = random.uniform(
                  FULL_QUEUE_PAUSE_MIN, FULL_QUEUE_PAUSE_MAX
              )
              full_queue_pause_until[hwnd] = time.time() + pause_sec
              log(
                  f"[Bậc {idx}] Hàng chờ đủ 5/5! Tạm ngưng check Alliance"
                  f" trong {pause_sec / 60:.1f} phút."
              )
              queue_full = True
              break

            smart_sleep(random.uniform(0.5, 0.8))

          if not queue_full:
            if joined_rallies == MAX_RALLIES_PER_SCAN:
              log(
                  f"[Bậc {idx}] Đã đạt giới hạn {MAX_RALLIES_PER_SCAN} rally"
                  " trong lượt quét."
              )
            ensure_world_map(sct, hwnd)
            if no_new_rally_found:
              wait_sec = random.uniform(NO_RALLY_PAUSE_MIN, NO_RALLY_PAUSE_MAX)
              log(
                  f"[Bậc {idx}] Không có rally mới sau {scroll_count} lần cuộn;"
                  f" nghỉ tab {wait_sec / 60:.1f} phút."
              )
        else:
          log(
              f"[Bậc {idx}] Lỗi mở Alliance -> War. Thử lại sau"
              f" {wait_sec:.0f}s."
          )

        schedule_next_scan(hwnd, wait_sec)
        smart_sleep(random.uniform(1.0, 1.5))

      smart_sleep(0.5)


def start_control_gui():
  global gui_root, gui_status_var

  gui_root = tk.Tk()
  gui_root.title("RoK Bot Control")
  gui_root.overrideredirect(True)
  gui_root.attributes("-topmost", True)
  gui_root.configure(bg="#1e1e1e")

  gui_status_var = tk.StringVar(value="Đang khởi động RoK Bot...")

  frame = tk.Frame(
      gui_root,
      bg="#1e1e1e",
      highlightbackground="#444444",
      highlightthickness=1,
      padx=8,
      pady=6,
  )
  frame.pack()

  lbl_status = tk.Label(
      frame,
      textvariable=gui_status_var,
      bg="#1e1e1e",
      fg="#00e676",
      font=("Segoe UI", 9, "bold"),
      width=36,
      anchor="w",
      cursor="fleur",
  )
  lbl_status.pack(side=tk.LEFT, padx=(2, 8))

  btn_stop = tk.Button(
      frame,
      text="🛑 TẮT BOT (F12)",
      command=lambda: stop_bot_now("Người dùng bấm nút TẮT BOT"),
      bg="#d93025",
      fg="white",
      activebackground="#a50e0e",
      activeforeground="white",
      font=("Segoe UI", 9, "bold"),
      relief=tk.FLAT,
      padx=10,
      pady=3,
      cursor="hand2",
  )
  btn_stop.pack(side=tk.RIGHT)

  drag_data = {"x": 0, "y": 0}

  def on_drag_start(event):
    drag_data["x"] = event.x
    drag_data["y"] = event.y

  def on_drag_motion(event):
    new_x = gui_root.winfo_x() + (event.x - drag_data["x"])
    new_y = gui_root.winfo_y() + (event.y - drag_data["y"])
    gui_root.geometry(f"+{new_x}+{new_y}")

  lbl_status.bind("<ButtonPress-1>", on_drag_start)
  lbl_status.bind("<B1-Motion>", on_drag_motion)

  gui_root.update_idletasks()
  screen_h = gui_root.winfo_screenheight()
  gui_root.geometry(f"+15+{screen_h - 95}")

  t = threading.Thread(target=bot_worker, daemon=True)
  t.start()

  gui_root.mainloop()


if __name__ == "__main__":
  os.chdir(os.path.dirname(os.path.abspath(__file__)))
  if not is_admin():
    print("CẢNH BÁO: Hãy mở bot bằng quyền Run as administrator!")
    print(
        "Nhấp phải shortcut của bot, chọn 'Run as administrator' rồi chạy lại."
    )
    input("Nhấn Enter để đóng cửa sổ...")
  elif check_templates():
    start_control_gui()
  else:
    input("Nhấn Enter để đóng cửa sổ...")