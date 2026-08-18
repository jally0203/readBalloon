# =====================================================================================
# VERSION: K-Protocol V20.3 (Heuristic Intelligence & Smart Diagnostic)
# DATE: 2026-03-03
# FEATURES: 
#   1. 智慧距離診斷 (Heuristic)：分析圖面球標間距規律，自動給予 config.ini 修正建議。
#   2. 嚴格配置讀取：不自動產生 config，確保數據受控。
#   3. 影子校驗 & 角度隔離：延續 V20.2 的強大防錯邏輯。
# =====================================================================================

import ezdxf
import math
import configparser
import os
import glob
import sys
from collections import Counter

def get_base_path():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def load_config(config_file="config.ini"):
    base_path = get_base_path()
    config_path = os.path.join(base_path, config_file)
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"❌ 找不到設定檔: {config_path}")
    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')
    s = config['SETTINGS']
    return {
        'COLOR': s.getint('COLOR'),
        'DIST_MIN': s.getfloat('DIST_RANGE_MIN'),
        'DIST_MAX': s.getfloat('DIST_RANGE_MAX'),
        'DIST_OFFSET': s.getfloat('DIST_OFFSET', fallback=2.0),
        'LIMMAX': (s.getfloat('LIMMAX_X'), s.getfloat('LIMMAX_Y')),
        'SEGMENT': (s.getint('SEGMENT_X'), s.getint('SEGMENT_Y')),
        'ANGLE_TOL': s.getfloat('ANGLE_TOLERANCE', fallback=0.5)
    }

def get_grid_location(x, y, cfg):
    lim_x, lim_y = cfg['LIMMAX']
    seg_x, seg_y = cfg['SEGMENT']
    grid_x = max(1, min(seg_x, math.ceil(x / (lim_x / seg_x))))
    y_labels = [chr(i) for i in range(65, 65 + seg_y)]
    grid_y_idx = max(0, min(len(y_labels)-1, int((lim_y - y) / (lim_y / seg_y))))
    return f"{y_labels[grid_y_idx]}{grid_x}"

def run_heuristic_diagnostic(balloons):
    """V20.3 新增：分析圖面球標間距規律，返回最可能的間距值"""
    samples = []
    for i in range(len(balloons)):
        for j in range(i + 1, len(balloons)):
            dx, dy = abs(balloons[i]['x'] - balloons[j]['x']), abs(balloons[i]['y'] - balloons[j]['y'])
            # 抓取具有對齊特徵的距離 (X 或 Y 其中一軸接近 0)
            if (dx > 5 and dy < 1.0) or (dy > 5 and dx < 1.0):
                dist = dx if dx > dy else dy
                samples.append(round(dist, 0))
    
    if not samples: return None
    most_common = Counter(samples).most_common(1)
    # 至少要有 3 組以上的樣本才具有統計代表性
    return most_common[0][0] if most_common[0][1] >= 3 else None

def audit_file(file_path, cfg):
    try:
        doc = ezdxf.readfile(file_path)
    except Exception as e: return f"❌ 無法讀取 {os.path.basename(file_path)}: {e}\n"

    msp = doc.modelspace()
    balloons = []
    for entity in msp.query('TEXT MTEXT'):
        rot = entity.dxf.rotation
        content = entity.plain_text().strip() if entity.dxftype() == 'MTEXT' else entity.dxf.text.strip()
        if content.isdigit() and entity.dxf.color == cfg['COLOR']:
            balloons.append({'id': int(content), 'x': round(entity.dxf.insert.x, 3), 
                             'y': round(entity.dxf.insert.y, 3), 'rot': round(rot, 2), 
                             'used': False, 'note': "SINGLE"})

    if not balloons: return f"\n📄 檔案: {os.path.basename(file_path)} -> ⚠ 未找到球標\n"

    # --- V20.3 智慧診斷 ---
    detected_dist = run_heuristic_diagnostic(balloons)
    smart_hint = ""
    if detected_dist and not (cfg['DIST_MIN'] <= detected_dist <= cfg['DIST_MAX']):
        smart_hint = (f"💡 [智慧建議]: 偵測到此圖面球標間距約為 {detected_dist}，"
                      f"與目前設定 ({cfg['DIST_MIN']}~{cfg['DIST_MAX']}) 不符。\n"
                      f"   建議調整 config.ini 為: DIST_RANGE_MIN={detected_dist-2}, DIST_RANGE_MAX={detected_dist+2}\n")

    id_counts = Counter([b['id'] for b in balloons])
    balloons.sort(key=lambda x: x['id'])
    final_items, covered_ids, range_zones = [], set(), []
    offset = cfg['DIST_OFFSET']

    # --- 第一階段：空間物理配對 ---
    for i in range(len(balloons)):
        if balloons[i]['used']: continue
        b1 = balloons[i]
        match_idx = -1
        for j in range(len(balloons)):
            if i == j or balloons[j]['used']: continue
            b2 = balloons[j]
            if abs(b1['rot'] - b2['rot']) > cfg['ANGLE_TOL']: continue
            dx, dy = b2['x'] - b1['x'], b2['y'] - b1['y']
            if ((abs(dy) < offset and cfg['DIST_MIN'] <= dx <= cfg['DIST_MAX']) or 
                (abs(dx) < offset and cfg['DIST_MIN'] <= dy <= cfg['DIST_MAX'])) and (b2['id'] > b1['id'] + 1):
                match_idx = j
                break
        
        if match_idx != -1:
            b2 = balloons[match_idx]
            label = f"{b1['id']}~{b2['id']}"
            final_items.append([label, get_grid_location(b1['x'], b1['y'], cfg), f"({b1['x']}, {b1['y']})", "RANGE (Spatial Match)"])
            range_zones.append((b1['id'], b2['id']))
            for v in range(b1['id'], b2['id'] + 1): covered_ids.add(v)
            b1['used'] = b2['used'] = True

    # --- 第二階段：影子校驗 ---
    for b in balloons:
        if b['used']: continue
        in_range = False
        for s, e in range_zones:
            if s <= b['id'] <= e:
                b['note'], in_range = f"⚠️ REDUNDANT (In {s}~{e})", True
                break
        if not in_range and id_counts[b['id']] > 1: b['note'] = "❌ DUPLICATE (Same ID)"
        final_items.append([str(b['id']), get_grid_location(b['x'], b['y'], cfg), f"({b['x']}, {b['y']})", b['note']])
        covered_ids.add(b['id'])
        b['used'] = True

    # --- 第三階段：報告生成 ---
    report = ["\n" + "="*110, f"📄 檔案: {os.path.basename(file_path)} (V20.3 AI Diagnostic)", "-" * 110]
    if smart_hint: report.append(smart_hint + "-" * 110)
    report.append(f"{'項目 (Item)':<18} | {'位置 (Grid)':<10} | {'座標 (Coordinate)':<25} | {'類型 (備註)'}\n" + "-" * 110)
    final_items.sort(key=lambda x: (int(x[0].split('~')[0])))
    actual_conflicts = [it[0].split('~')[0] for it in final_items if "⚠️" in it[3] or "❌" in it[3]]
    for it in final_items: report.append(f"{it[0]:<18} | {it[1]:<10} | {it[2]:<25} | {it[3]}")
    report.append("-" * 110)
    report.append(f"❌ 衝突偵測: {', '.join(sorted(list(set(actual_conflicts)))) if actual_conflicts else '✅ 完美'}")
    max_id = max(covered_ids) if covered_ids else 0
    missing = [n for n in range(1, max_id + 1) if n not in covered_ids]
    report.append(f"❓ 缺失 (1~{max_id}): {', '.join(map(str, missing)) if missing else '✅ 完整'}\n" + "="*110)
    return "\n".join(report) + "\n"

def main():
    base_path = get_base_path()
    try:
        cfg = load_config()
        dxf_files = glob.glob(os.path.join(base_path, "*.dxf"))
        full_report = "".join([audit_file(f, cfg) for f in dxf_files])
        print(full_report)
        with open(os.path.join(base_path, "output.txt"), "w", encoding="utf-8") as f: f.write(full_report)
    except Exception as e: print(f"\n{e}")
    if getattr(sys, 'frozen', False): input("\n執行結束...")

if __name__ == "__main__": main()
