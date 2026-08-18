# =====================================================================================
# VERSION: K-Protocol V20.2 (Strict Config & Shadow Audit)
# DATE: 2026-03-03
# MODIFICATION: 移除自動產生 config.ini 功能，改為嚴格讀取模式。
# =====================================================================================

import ezdxf
import math
import configparser
import os
import glob
import sys
from collections import Counter

def get_base_path():
    """獲取執行路徑，支援封裝後的 EXE 環境"""
    if getattr(sys, 'frozen', False): 
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def load_config(config_file="config.ini"):
    """嚴格讀取配置檔，若不存在則拋出致命錯誤"""
    base_path = get_base_path()
    config_path = os.path.join(base_path, config_file)
    
    if not os.path.exists(config_path):
        # V20.2 嚴格模式：不再自動產生，改為報錯
        raise FileNotFoundError(f"致命錯誤：找不到設定檔 {config_path}，請確認檔案是否存在。")
        
    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')
    
    if 'SETTINGS' not in config:
        raise ValueError(f"致命錯誤：設定檔 {config_file} 格式錯誤，缺少 [SETTINGS] 區段。")
        
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
    """計算球標在圖紙上的座標索引 (如 A1, B4)"""
    lim_x, lim_y = cfg['LIMMAX']
    seg_x, seg_y = cfg['SEGMENT']
    
    grid_x = math.ceil(x / (lim_x / seg_x))
    grid_x = max(1, min(seg_x, grid_x))
    
    y_labels = [chr(i) for i in range(65, 65 + seg_y)]
    grid_y_idx = int((lim_y - y) / (lim_y / seg_y))
    grid_y_idx = max(0, min(len(y_labels)-1, grid_y_idx))
    
    return f"{y_labels[grid_y_idx]}{grid_x}"

def audit_file(file_path, cfg):
    """核心審核邏輯：結合物理距離、角度與全域計數"""
    try:
        doc = ezdxf.readfile(file_path)
    except Exception as e: 
        return f"❌ 無法讀取 {os.path.basename(file_path)}: {e}\n"

    msp = doc.modelspace()
    balloons = []
    
    for entity in msp.query('TEXT MTEXT'):
        rot = entity.dxf.rotation
        if entity.dxftype() == 'MTEXT':
            content = entity.plain_text().strip()
        else:
            content = entity.dxf.text.strip()
            
        if content.isdigit() and entity.dxf.color == cfg['COLOR']:
            balloons.append({
                'id': int(content),
                'x': round(entity.dxf.insert.x, 3),
                'y': round(entity.dxf.insert.y, 3),
                'rot': round(rot, 2),
                'used': False,
                'note': "SINGLE"
            })

    if not balloons:
        return f"\n📄 檔案: {os.path.basename(file_path)} -> ⚠ 未找到符合顏色 {cfg['COLOR']} 的球標\n"

    id_counts = Counter([b['id'] for b in balloons])
    balloons.sort(key=lambda x: x['id'])
    
    final_items = []
    covered_ids = set()
    range_zones = [] 
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
            is_match = ( (abs(dy) < offset and cfg['DIST_MIN'] <= dx <= cfg['DIST_MAX']) or 
                         (abs(dx) < offset and cfg['DIST_MIN'] <= dy <= cfg['DIST_MAX']) )
            
            # 嚴格 ID 順序判定
            if is_match and (b2['id'] > b1['id'] + 1):
                match_idx = j
                break
        
        if match_idx != -1:
            b2 = balloons[match_idx]
            label = f"{b1['id']}~{b2['id']}"
            loc = get_grid_location(b1['x'], b1['y'], cfg)
            final_items.append([label, loc, f"({b1['x']}, {b1['y']})", "RANGE (Spatial Match)"])
            range_zones.append((b1['id'], b2['id']))
            for v in range(b1['id'], b2['id'] + 1): 
                covered_ids.add(v)
            b1['used'] = b2['used'] = True

    # --- 第二階段：影子校驗 ---
    for b in balloons:
        if b['used']: continue
        in_range = False
        for start, end in range_zones:
            if start <= b['id'] <= end:
                b['note'] = f"⚠️ REDUNDANT (In {start}~{end})"
                in_range = True
                break
        
        if not in_range and id_counts[b['id']] > 1:
            b['note'] = "❌ DUPLICATE (Same ID)"

        loc = get_grid_location(b['x'], b['y'], cfg)
        final_items.append([str(b['id']), loc, f"({b['x']}, {b['y']})", b['note']])
        covered_ids.add(b['id'])
        b['used'] = True

    # --- 第三階段：報告生成 ---
    report = ["\n" + "="*110, f"📄 檔案: {os.path.basename(file_path)} (V20.2 Premium)", "-" * 110]
    report.append(f"{'項目 (Item)':<18} | {'位置 (Grid)':<10} | {'座標 (Coordinate)':<25} | {'類型 (備註)'}")
    report.append("-" * 110)
    
    final_items.sort(key=lambda x: (int(x[0].split('~')[0])))
    
    actual_conflicts = []
    for item in final_items:
        report.append(f"{item[0]:<18} | {item[1]:<10} | {item[2]:<25} | {item[3]}")
        if "⚠️" in item[3] or "❌" in item[3]:
            actual_conflicts.append(item[0].split('~')[0])

    report.append("-" * 110)
    report.append(f"❌ 衝突偵測 (含多打): {', '.join(sorted(list(set(actual_conflicts)))) if actual_conflicts else '✅ 完美'}")
    
    max_id = max(covered_ids) if covered_ids else 0
    missing = [n for n in range(1, max_id + 1) if n not in covered_ids]
    report.append(f"❓ 缺失 (1~{max_id}): {', '.join(map(str, missing)) if missing else '✅ 完整'}")
    report.append("="*110)
    
    return "\n".join(report) + "\n"

def main():
    base_path = get_base_path()
    output_path = os.path.join(base_path, "output.txt")
    try:
        cfg = load_config()
        dxf_files = glob.glob(os.path.join(base_path, "*.dxf"))
        
        if not dxf_files:
            print(f"⚠ 在路徑下找不到任何 DXF 檔案：{base_path}")
            return

        full_report = ""
        for f in dxf_files:
            res = audit_file(f, cfg)
            print(res)
            full_report += res
            
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_report)
            
    except Exception as e:
        print(f"\n{e}") # 直接輸出錯誤訊息（如：找不到設定檔）
        
    if getattr(sys, 'frozen', False):
        input("\n執行結束，請按 Enter 鍵結束...")

if __name__ == "__main__":
    main()
