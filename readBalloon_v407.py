import os
import configparser
import math
import re
import ezdxf
from ezdxf.math import Vec3, Matrix44

DEBUG = True  #是否要印出debue資訊
OUTPUT_CSV = True  #同時輸出成CSV 
DEBUG_BALL_ID = 141   # 察看特定球標配對情形，0 = disable
_debugEnable_ = False  # 不要修改，指定DEBUG_BALL_ID後自動啟用

# ==========================================
# 1. 設定檔讀取與 DXF 文字清理
# ==========================================
def load_config(config_file='config.ini'):
    config = configparser.ConfigParser(inline_comment_prefixes=';')
    if not os.path.exists(config_file):
        print(f"❌ 找不到設定檔: {config_file}")
        return None
    
    config.read(config_file, encoding='utf-8')
    cfg = {}
    try:
        cfg['COLOR'] = config.getint('FILTER', 'COLOR', fallback=4)
        cfg['MIN_DIST'] = config.getfloat('FILTER', 'MIN_DIST', fallback=17.5)
        cfg['MAX_DIST'] = config.getfloat('FILTER', 'MAX_DIST', fallback=20.5)
        cfg['ORTHO_TOL'] = config.getfloat('FILTER', 'ORTHO_TOL', fallback=1.0)
        cfg['TOLERANCE_ROT'] = config.getfloat('FILTER', 'TOLERANCE_ROT', fallback=2.0)
        cfg['MAX_MATCH_DIST'] = config.getfloat('FILTER', 'MAX_MATCH_DIST', fallback=350.0)
        cfg['MAX_RIGHT_SIDE_DIST'] = config.getfloat('FILTER', 'MAX_RIGHT_SIDE_DIST', fallback=50.0)
        cfg['MAX_BOTTOM_SIDE_DIST'] = config.getfloat('FILTER', 'MAX_BOTTOM_SIDE_DIST', fallback=20.0)
        cfg['MAX_PPK_DIST'] = config.getfloat('FILTER', 'MAX_PPK_DIST', fallback=20.0)
    except Exception as e:
        print(f"❌ 設定檔讀取錯誤: {e}")
        return None
    return cfg

def clean_dxf_text(text):
    text = re.sub(r'\\[a-zA-Z0-9]+;', '', text)
    text = re.sub(r'\\[fFpP0-9a-zA-Z]+;', '', text)
    text = re.sub(r'\\P', ' ', text)
    text = re.sub(r'[{}]', '', text)
    return text.strip()

def get_effective_color(entity, doc, parent_color=None):
    color = entity.dxf.color
    if color == 256:
        layer_name = entity.dxf.layer
        if layer_name in doc.layers:
            color = doc.layers.get(layer_name).dxf.color
    elif color == 0:
        if parent_color is not None:
            color = parent_color
    return color

# ======================
# 同時處理符號 填滿<> 並代入更多文字資訊 
# ======================
def clean_dxf_text(raw_text):
    """清理 DXF 特殊字串與轉義符號"""
    if not raw_text:
        return ""
    text = raw_text.replace("%%c", "∅").replace("%%C", "∅")
    text = text.replace("%%p", "±").replace("%%P", "±")
    text = text.replace("%%d", "°").replace("%%D", "°")
    text = text.replace("%%u", "").replace("%%U", "")
    text = text.replace("%%o", "").replace("%%O", "")
    text = text.replace("%%%%", "%")
    return text.strip()

import math


def find_entities_in_layout(
    layout,
    doc,
    target_color,
    transform=Matrix44(),
    parent_color=None,
    balloons=None,
    dim_texts=None,
    dimensions=None,
):
    if balloons is None:
        balloons = []
    if dim_texts is None:
        dim_texts = []
    if dimensions is None:
        dimensions = []

    for entity in layout:
        dxftype = entity.dxftype()

        # ==========================================
        # 1. 處理 TEXT / MTEXT
        # ==========================================
        if dxftype in ("TEXT", "MTEXT"):
            raw_text = (
                entity.plain_text()
                if dxftype == "MTEXT"
                else entity.dxf.text
            )
            content = clean_dxf_text(raw_text)
            if not content:
                continue

            eff_color = get_effective_color(entity, doc, parent_color)

            local_insert = (
                entity.dxf.align_point
                if entity.dxf.hasattr("align_point")
                and entity.dxf.align_point != (0, 0, 0)
                else entity.dxf.insert
            )
            local_rot = (
                entity.dxf.rotation if entity.dxf.hasattr("rotation") else 0.0
            )

            wcs_insert = transform.transform(local_insert)
            v_rot = transform.transform_direction(
                Vec3.from_deg_angle(local_rot)
            )
            wcs_rot = math.degrees(math.atan2(v_rot.y, v_rot.x)) % 360.0

            # Balloon 條件過濾
            if content.isdigit() and eff_color == target_color:
                balloons.append({
                    "id": int(content),
                    "x": round(wcs_insert.x, 3),
                    "y": round(wcs_insert.y, 3),
                    "rot": round(wcs_rot, 2),
                })
            else:
                dim_texts.append({
                    "text": content,
                    "x": round(wcs_insert.x, 3),
                    "y": round(wcs_insert.y, 3),
                    "rot": round(wcs_rot, 2),
                    "color": eff_color,
                    "handle": entity.dxf.handle
                    if entity.dxf.hasattr("handle")
                    else None,
                    "style_name": entity.dxf.style
                    if entity.dxf.hasattr("style")
                    else "STANDARD",
                })

        # ==========================================
        # 2. 處理 DIMENSION (尺寸標註)
        # ==========================================
        elif dxftype == "DIMENSION":
            eff_color = get_effective_color(entity, doc, parent_color)

            # --- 解析 基本屬性 與 位置 ---
            override_text = (
                clean_dxf_text(entity.dxf.text)
                if entity.dxf.hasattr("text")
                else ""
            )
            pos = (
                entity.dxf.text_midpoint
                if entity.dxf.hasattr("text_midpoint")
                and entity.dxf.text_midpoint != (0, 0, 0)
                else entity.dxf.defpoint
            )
            wcs_pos = transform.transform(pos)

            dim_handle = (
                entity.dxf.handle if entity.dxf.hasattr("handle") else None
            )
            dim_style = (
                entity.dxf.dimstyle
                if entity.dxf.hasattr("dimstyle")
                else "STANDARD"
            )

            # --- 定義點座標 (WCS) ---
            defpoint = (
                transform.transform(entity.dxf.defpoint)
                if entity.dxf.hasattr("defpoint")
                else None
            )
            defpoint2 = (
                transform.transform(entity.dxf.defpoint2)
                if entity.dxf.hasattr("defpoint2")
                else None
            )
            defpoint3 = (
                transform.transform(entity.dxf.defpoint3)
                if entity.dxf.hasattr("defpoint3")
                else None
            )

            # ---------------------------------------------------------
            # 1. 讀取幾何測量值與比例因子 (DIMLFAC)，並根據 dimtype 計算 CAD 實際顯示值
            # ---------------------------------------------------------
            geom_measurement = (
                entity.dxf.get("actual_measurement", None)
                if entity.dxf.hasattr("actual_measurement")
                else (
                    entity.get_measurement()
                    if hasattr(entity, "get_measurement")
                    else None
                )
            )

            scale_factor = 1.0
            if entity.dxf.hasattr("dimlfac"):
                scale_factor = entity.dxf.dimlfac
            elif dim_style in doc.dimstyles:
                dimstyle_obj = doc.dimstyles.get(dim_style)
                if dimstyle_obj and dimstyle_obj.dxf.hasattr("dimlfac"):
                    scale_factor = dimstyle_obj.dxf.dimlfac

            if scale_factor == 0:
                scale_factor = 1.0

            # 取得 dimtype 屬性 (優先從 ezdxf 物件讀取，沒有則預設 0)
            dimtype = (
                entity.dimtype
                if hasattr(entity, "dimtype")
                else entity.dxf.get("dimtype", 0)
            )
            core_type = (
                dimtype & 7 if dimtype is not None else 0
            )  # 提取核心標註類型 (遮罩 0x07)

            cad_display_val = None
            cad_display_str = ""

            if geom_measurement is not None and geom_measurement >= 0:
                # 角度標註：2 (Angular) 與 5 (Angular 3-Point)
                if core_type in (2, 5):
                    cad_display_val = math.degrees(geom_measurement)  # 弧度轉角度
                    cad_display_str = f"{cad_display_val:.1f}"  # 角度習慣保留 1 位小數 (如 90.0)
                else:
                    # 一般長度標註：幾何測量值 / scale_factor
                    #cad_display_val = geom_measurement / scale_factor
                    cad_display_val = geom_measurement
                    cad_display_str = f"{cad_display_val:.2f}"  # 長度習慣保留 2 位小數

            # ---------------------------------------------------------
            # 2. 讀取公差
            # ---------------------------------------------------------
            tol_plus = (
                entity.dxf.get("dimtp", None)
                if entity.dxf.hasattr("dimtp")
                else None
            )
            tol_minus = (
                entity.dxf.get("dimtm", None)
                if entity.dxf.hasattr("dimtm")
                else None
            )

            if (
                tol_plus is None or tol_minus is None
            ) and dim_style in doc.dimstyles:
                dimstyle_obj = doc.dimstyles.get(dim_style)
                if dimstyle_obj:
                    has_tol = dimstyle_obj.dxf.get(
                        "dimtol", 0
                    ) or dimstyle_obj.dxf.get("dimlim", 0)
                    if has_tol:
                        if tol_plus is None and dimstyle_obj.dxf.hasattr(
                            "dimtp"
                        ):
                            tol_plus = dimstyle_obj.dxf.dimtp
                        if tol_minus is None and dimstyle_obj.dxf.hasattr(
                            "dimtm"
                        ):
                            tol_minus = dimstyle_obj.dxf.dimtm

            tol_str = ""
            if tol_plus is not None and tol_minus is not None:
                tp = float(tol_plus)
                tm = float(tol_minus)
                if tp != 0 or tm != 0:
                    if abs(tp) == abs(tm):
                        tol_str = f"±{abs(tp):.2f}"
                    else:
                        tol_str = f"(+{tp:.2f}/-{abs(tm):.2f})"

# ---------------------------------------------------------
            # 3. 組合文字內容 (替換 <> 佔位符)
            # ---------------------------------------------------------
            # 判斷是否為角度標註 (2 與 5)
            is_angular = core_type in (2, 5)
            deg_symbol = "°" if is_angular else ""

            if override_text:
                if "<>" in override_text:
                    # 情形 1：有手動覆寫且保留 <> (例如 "2X <>")
                    # 產出例如："2X <>#90.0°±1.00"
                    final_dim_text = (
                        f"{override_text}#{cad_display_str}{deg_symbol}{tol_str}"
                    )
                else:
                    # 情形 2：硬改文字且抹除 <> (例如 "TYP.")
                    # 產出例如："TYP.±1.00"
                    final_dim_text = f"{override_text}{tol_str}"
            else:
                # 情形 3：完全無手動覆寫 (CAD 預設)
                # 產出例如："<>#90.0°±1.00"
                final_dim_text = f"<>#{cad_display_str}{deg_symbol}{tol_str}{deg_symbol}"

            # 寫入 dim_texts 串列
            if final_dim_text:
                dim_texts.append({
                    "text": final_dim_text,
                    "x": round(wcs_pos.x, 3),
                    "y": round(wcs_pos.y, 3),
                    "rot": 0.0,
                    "color": eff_color,
                    "handle": dim_handle,
                    "style_name": dim_style,
                })

            # ---------------------------------------------------------
            # 4. 存入 dimensions 詳細變數
            # ---------------------------------------------------------
            dimensions.append({
                "handle": dim_handle,
                "dimstyle": dim_style,
                "color": eff_color,
                "dimtype": dimtype,
                "raw_text": override_text,
                "final_text": final_dim_text,
                "cad_display_value": round(cad_display_val, 3)
                if cad_display_val is not None
                else None,
                "geom_measurement": round(geom_measurement, 3)
                if geom_measurement is not None
                else None,
                "scale_factor": scale_factor,
                "tolerance": {
                    "plus": float(tol_plus) if tol_plus is not None else 0.0,
                    "minus": float(tol_minus) if tol_minus is not None else 0.0,
                    "text": tol_str,
                },
                "text_position": {
                    "x": round(wcs_pos.x, 3),
                    "y": round(wcs_pos.y, 3),
                },
                "defpoints": {
                    "defpoint": (
                        round(defpoint.x, 3),
                        round(defpoint.y, 3),
                    )
                    if defpoint
                    else None,
                    "defpoint2": (
                        round(defpoint2.x, 3),
                        round(defpoint2.y, 3),
                    )
                    if defpoint2
                    else None,
                    "defpoint3": (
                        round(defpoint3.x, 3),
                        round(defpoint3.y, 3),
                    )
                    if defpoint3
                    else None,
                },
            })

        # ==========================================
        # 3. 處理 INSERT (圖塊引用 + 遞迴)
        # ==========================================
        elif dxftype == "INSERT":
            insert_color = get_effective_color(entity, doc, parent_color)
            insert_matrix = entity.matrix44()
            combined_transform = insert_matrix * transform

            if hasattr(entity, "attribs"):
                for attrib in entity.attribs:
                    attr_text = clean_dxf_text(attrib.dxf.text)
                    if not attr_text:
                        continue

                    attr_color = get_effective_color(
                        attrib, doc, insert_color
                    )
                    wcs_attr_pos = combined_transform.transform(
                        attrib.dxf.insert
                    )

                    if attr_text.isdigit() and attr_color == target_color:
                        balloons.append({
                            "id": int(attr_text),
                            "x": round(wcs_attr_pos.x, 3),
                            "y": round(wcs_attr_pos.y, 3),
                            "rot": 0.0,
                        })
                    else:
                        dim_texts.append({
                            "text": attr_text,
                            "x": round(wcs_attr_pos.x, 3),
                            "y": round(wcs_attr_pos.y, 3),
                            "rot": 0.0,
                            "color": attr_color,
                            "handle": attrib.dxf.handle
                            if attrib.dxf.hasattr("handle")
                            else None,
                            "style_name": attrib.dxf.style
                            if attrib.dxf.hasattr("style")
                            else "STANDARD",
                        })

            block_name = entity.dxf.name
            if block_name in doc.blocks:
                block = doc.blocks[block_name]
                find_entities_in_layout(
                    layout=block,
                    doc=doc,
                    target_color=target_color,
                    transform=combined_transform,
                    parent_color=insert_color,
                    balloons=balloons,
                    dim_texts=dim_texts,
                    dimensions=dimensions,
                )

    return balloons, dim_texts, dimensions

# ==========================================
# 3. 幾何約束檢查與尺寸匹配
# ==========================================
def calc_distance(b1, b2):
    return math.hypot(b1['x'] - b2['x'], b1['y'] - b2['y'])

def calc_rot_diff(r1, r2):
    diff = abs(r1 - r2) % 360.0
    return min(diff, 360.0 - diff)

# 計算2物件相對位置(dx, dy)轉到水平線的XY值  
def calLocalXY(rot, dx, dy):  
    rad = math.radians(rot)
    cos_angle = math.cos(rad)
    sin_angle = math.sin(rad)
    ret_x = dx * cos_angle + dy * sin_angle
    ret_y = -dx * sin_angle + dy * cos_angle
    return ret_x, ret_y

def is_valid_range_geometry(b1, b2, cfg):
    if calc_rot_diff(b1['rot'], b2['rot']) > cfg.get('TOLERANCE_ROT', 2.0):
        return False

    dx = abs(b1['x'] - b2['x'])
    dy = abs(b1['y'] - b2['y'])
    local_x, local_y = calLocalXY(b1['rot'], dx, dy)
    
    if local_y > cfg['ORTHO_TOL']:
        return False

    if not (cfg['MIN_DIST'] <= local_x <= cfg['MAX_DIST']):
        return False    
    
    return True

def find_closest_number_for_prefix(prefix_frag, all_dim_texts):
    """專為 RANGE 設計：尋找距離 N- 碎片最近且格式符合小數的數字"""
    px, py = prefix_frag['x'], prefix_frag['y']
    best_num = None
    min_dist = 999999.0

    for t in all_dim_texts:
        if t == prefix_frag:
            continue
        txt = t['text'].strip()
        # 匹配小數或數字 (例如 1.30, 0.05)
        if re.match(r'^\d+(\.\d+)?$', txt):
            dx = abs(t['x'] - px)
            dy = abs(t['y'] - py)
            if dx <= 50.0 and dy <= 25.0:
                dist = math.hypot(dx, dy)
                if dist < min_dist:
                    min_dist = dist
                    best_num = txt
    return best_num

def getPPKItems(dim_texts):
    return [item for item in dim_texts if item.get("text") == "PPK"]
   
def findRightSideRect(bx, by, b_rot, dim_texts, rect, expected_prefix):
    width, height = rect
    half_h = height / 2.0
    if _debugEnable_:
        print(f'  - matching balloon (x, y, rot) = ({bx}, {by}, {b_rot})')
    
    # 先將符合字串前綴的項目與其轉換後的局部座標預先計算出來
    candidates = []
    for item in dim_texts:
        text = str(item.get("text", ""))
        if text.find(expected_prefix) >= 0: #text.startswith(expected_prefix):
            px = item.get("x", 0)
            py = item.get("y", 0)
            dx = px - bx
            dy = py - by
            
            # 逆向旋轉 -b_rot 角度（轉換至 0 度局部座標系）
            local_x, local_y =  calLocalXY(b_rot, dx, dy)            
               
            # Y 軸範圍始終為 [-height/2, height/2]
            if -half_h <= local_y <= half_h:
                candidates.append((local_x, text))
                if _debugEnable_:
                    print(f'  - candidate added: (x, y, text) = ({px}, {py}, {text})')
                
    # 階段 1：搜尋右側 [0, width]
    if _debugEnable_:
        print(f'  - start find right side')        
    for local_x, text in candidates:
        if 0 <= local_x <= width:
            if _debugEnable_:
                print(f'    - found {text}, return')
            return True, text
            
    # 階段 2：右側找不到，改搜尋左側 [-width, 0]
    if _debugEnable_:
        print(f'  - start find left side')
    for local_x, text in candidates:
        if -width <= local_x <= 0:
            if _debugEnable_:
                print(f'    - found {text}, return')
            return True, text
            
    return False, None

def findWindowClosest(bx, by, b_rot, dim_texts, max_match_dist, expected_prefix):
    closest_txt = None
    min_dist_sq = max_match_dist ** 2  # 使用距離平方比對，省去開根號計算
    if _debugEnable_:
        print(f'  - matching balloon (x, y, rot) = ({bx}, {by}, {b_rot})')
        
    for item in dim_texts:
        text = str(item.get("text", ""))
        
        # 先過濾前綴條件
        if text.find(expected_prefix) >= 0:  #text.startswith(expected_prefix):
            px = item.get("x", 0)
            py = item.get("y", 0)
            
            dx = px - bx
            dy = py - by
            dist_sq = dx * dx + dy * dy
            
            # 判斷是否落在距離內且比當前找到的更近
            if dist_sq <= min_dist_sq:
                min_dist_sq = dist_sq
                closest_txt = text
                
    if closest_txt is not None:
        if _debugEnable_:
            print(f'    - found {closest_txt}, return')
        return True, closest_txt
        
    return False, None
  
def findPPK(bx, by, b_rot, ppk_items, max_ppk_dist):
    
    for item in ppk_items:
        dx = item.get("x", 0) - bx
        dy = item.get("y", 0) - by
        
        # 將相對座標逆向旋轉 -b_rot 角度（適用於螢幕座標系 Y 軸向下）
        local_x, local_y = calLocalXY(b_rot, dx, dy)
        
        # 無論 b_rot 是 0、18、45 還是 87.5 度，判斷範圍永遠不變
        if 0 <= local_x <= max_ppk_dist and -10 <= local_y <= 10:
            return True
            
    return False

def remove_mark(text):
    if not text or "<>" not in text or "#" not in text:
        return text
        
    # 利用正則表達式拆解：
    # group(1): <> 前面的文字 (如 "5-")
    # group(2): <> 到 # 之間的文字 (如 ", LGA")
    # group(3): # 後面的文字 (如 "330+0.15")
    match = re.match(r"^(.*?)<>\s*(.*?)\s*#(.*)$", text)
    if match:
        prefix, middle, hash_text = match.groups()
        return f"{prefix}{hash_text.strip()}{middle.strip()}"
        
    return text
    

def match_range_dimension(current_item, dim_texts, ppk_items, cfg):
    global _debugEnable_ 
    start_id = current_item.get('start', current_item['id'])
    end_id = current_item.get('end', current_item['id'])
    balloon_count = abs(end_id - start_id) + 1
    
    print(f'matching {start_id}~{end_id}')
    if balloon_count <= 1:
        return "N/A"

    expected_prefix = f"{balloon_count}-"
    bx, by = current_item['x'], current_item['y']
    b_rot = current_item.get('rot', 0.0) % 360.0
    MAX_MATCH_DIST = cfg.get('MAX_MATCH_DIST', 5.0)
    MAX_RIGHT_SIDE_DIST = cfg.get('MAX_RIGHT_SIDE_DIST', 5.0)
    MAX_BOTTOM_SIDE_DIST = cfg.get('MAX_BOTTOM_SIDE_DIST', 5.0)
    MAX_PPK_DIST = cfg.get('MAX_PPK_DIST', 5.0)
    
    is_ppk = findPPK(bx, by, b_rot, ppk_items, MAX_PPK_DIST)
    return_text = "" if not is_ppk else "ppk,"
    
    rect = (MAX_RIGHT_SIDE_DIST, MAX_BOTTOM_SIDE_DIST)
    
    if DEBUG_BALL_ID == end_id:
        _debugEnable_ = True
        print(f'ID {DEBUG_BALL_ID}: look inside findRightSideRect')
    else:
        _debugEnable_ = False
       
    is_found, found_txt = findRightSideRect(bx, by, b_rot, dim_texts, rect, expected_prefix)
    if is_found:
        return_text += found_txt        
    else:
        if _debugEnable_:
            print(f'ID {DEBUG_BALL_ID}: look inside findWindowClosest')
        is_found, found_txt = findWindowClosest(bx, by, b_rot, dim_texts, MAX_MATCH_DIST, expected_prefix)
        if is_found:
            return_text += found_txt            
        else:
            return_text += "not Found!"
    
    return_text = remove_mark(return_text)  # 移除 <> 及 # 符號     
    return return_text


def match_single_dimension(current_item, dim_texts, ppk_items, cfg):
    global _debugEnable_
    start_id = current_item.get('start', current_item['id'])
    expected_prefix = f"<>"
    bx, by = current_item['x'], current_item['y']
    b_rot = current_item.get('rot', 0.0) % 360.0
    MAX_MATCH_DIST = cfg.get('MAX_MATCH_DIST', 5.0)
    MAX_RIGHT_SIDE_DIST = cfg.get('MAX_RIGHT_SIDE_DIST', 5.0)
    MAX_BOTTOM_SIDE_DIST = cfg.get('MAX_BOTTOM_SIDE_DIST', 5.0)
    MAX_PPK_DIST = cfg.get('MAX_PPK_DIST', 5.0)
    
    is_ppk = findPPK(bx, by, b_rot, ppk_items, MAX_PPK_DIST)
    return_text = "" if not is_ppk else "ppk, "
    
    if DEBUG_BALL_ID == start_id:
        _debugEnable_ = True
        print(f'ID {DEBUG_BALL_ID}: look inside findRightSideRect')
    else:
        _debugEnable_ = False
    
    rect = (MAX_RIGHT_SIDE_DIST, MAX_BOTTOM_SIDE_DIST)    
    is_found, found_txt = findRightSideRect(bx, by, b_rot, dim_texts, rect, expected_prefix)
    if is_found:
        return_text += found_txt
    else:    
        if _debugEnable_:
            print(f'ID {DEBUG_BALL_ID}: look inside findWindowClosest')
        is_found, found_txt = findWindowClosest(bx, by, b_rot, dim_texts, MAX_MATCH_DIST, expected_prefix)
        if is_found:
            return_text += found_txt
        else:
            return_text += "not Found!"
    
    # 找不到<>開頭可能是被手動修改
    pos = return_text.find("not Found!")
    if  pos >= 0:
        return_text = return_text[0:pos]
        if _debugEnable_:
            print(f'ID {DEBUG_BALL_ID}: cannot find <>, replaced by none, look inside findWindowClosest again')
        expected_prefix = ""
        is_found, found_txt = findWindowClosest(bx, by, b_rot, dim_texts, MAX_MATCH_DIST, expected_prefix)
        if is_found:
            return_text += found_txt
        else:
            return_text += "not Found!"    
    
    return_text = remove_mark(return_text)  # 移除 <> 及 # 符號     
    return return_text

# ==========================================
# 4. 主稽核函式（清單合併與最終報表）
# ==========================================
def audit_file(filepath, cfg):
    print(f"\n==========================================")
    print(f"📂 正在稽核檔案: {os.path.basename(filepath)}")
    print(f"==========================================")

    try:
        doc = ezdxf.readfile(filepath)
    except Exception as e:
        print(f"❌ 讀取 DXF 失敗: {e}")
        return

    msp = doc.modelspace()
    raw_balloons, dim_texts, dimensions = find_entities_in_layout(msp, doc, target_color=cfg['COLOR'])    

    if not raw_balloons:
        print("⚠ 未找到符合條件的球標文字。")
        return
          
    print(f"🔍 捕捉到 {len(raw_balloons)} 個數字球標，開始進行 SWAP 規則與物理距離配對...\n")
    if DEBUG:
        dfid = open('debug.txt', 'w', encoding='utf-8-sig')
        dfid.write('\nballoon: ')
        dfid.write(str(raw_balloons))
        dfid.write('\ndim_texts: ')
        dfid.write(str(dim_texts)) 
        dfid.write('\ndimensions: ')
        dfid.write(str(dimensions))
        dfid.close()

    # 1. 進行範圍球標幾何配對
    range_pairs = []
    used_indices = set()

    sorted_raw = sorted(raw_balloons, key=lambda x: x['id'])
    for i in range(len(sorted_raw)):
        if i in used_indices:
            continue
        b1 = sorted_raw[i]
        for j in range(i + 1, len(sorted_raw)):
            if j in used_indices:
                continue
            b2 = sorted_raw[j]

            if is_valid_range_geometry(b1, b2, cfg):   # 判斷2個球標是否在配對條件內，這裡尚未判斷2球標中間有無~符號
                start_id, end_id = min(b1['id'], b2['id']), max(b1['id'], b2['id'])
                start_b = b1 if b1['id'] == start_id else b2
                end_b = b2 if b2['id'] == end_id else b1
                
                range_pairs.append({
                    'id': start_id,
                    'display_id': f"{start_id}~{end_id}",
                    'x': end_b['x'],
                    'y': end_b['y'],
                    'rot': start_b['rot'],
                    'status': 'RANGE',
                    'start': start_id,
                    'end': end_id
                })
                used_indices.add(i)
                used_indices.add(j)
                break

    # 2. 將剩餘未匹配的標記為 SINGLE
    single_items = []
    for idx, b in enumerate(sorted_raw):
        if idx not in used_indices:
            single_items.append({
                'id': b['id'],
                'display_id': str(b['id']),
                'x': b['x'],
                'y': b['y'],
                'rot': b['rot'],
                'status': 'SINGLE',
                'start': b['id'],
                'end': b['id']
            })

    # 3. 合併所有項並按起始 ID 排序
    final_list = sorted(range_pairs + single_items, key=lambda item: item['id'])

    # 4. 進行尺寸匹配 (區分 RANGE 與 SINGLE)
    ppk_items = getPPKItems(dim_texts)  
    
    for item in final_list:
        if item['status'] == 'RANGE':
            item['match_result'] = match_range_dimension(item, dim_texts, ppk_items, cfg)  # 取得匹配的公差文字            
        else:
            item['match_result'] = match_single_dimension(item, dim_texts, ppk_items, cfg)

    # 5. 印出【球標詳細清單】
    print("📋 【球標詳細清單】")
    print(f"{'ID':<8} | {'X 座標':<10} | {'Y 座標':<10} | {'球標角度':<6} | {'尺寸公差'}")
    print("-" * 60)
    for item in final_list:
        print(f"{item['display_id']:<8} | {item['x']:<10.2f} | {item['y']:<10.2f} | {item['rot']:<6.1f} | {item['match_result']}")

    if OUTPUT_CSV:
        fid = open("output.csv", "w", encoding='utf-8-sig')
        fid.write("ID,X座標,Y座標,球標角度,尺寸公差\n")
        for item in final_list:
            fid.write(f"{item['display_id']},{item['x']:<.2f},{item['y']:<.2f},{item['rot']:<.1f},{item['match_result']}\n") 

    # 6. 計算涵蓋範圍、缺失與重複警告
    covered_counts = {}
    for item in final_list:
        for num in range(item['start'], item['end'] + 1):
            covered_counts[num] = covered_counts.get(num, 0) + 1

    duplicate_covered = [num for num, count in covered_counts.items() if count > 1]
    raw_ids = [b['id'] for b in raw_balloons]
    raw_duplicates = [x for x in raw_ids if raw_ids.count(x) > 1]

    all_duplicates = sorted(list(set(duplicate_covered + raw_duplicates)))
    all_covered_ids = set(covered_counts.keys())
    max_id = max(all_covered_ids) if all_covered_ids else 0
    missing_ids = [i for i in range(1, max_id + 1) if i not in all_covered_ids]

    # 7. 印出【統計與稽核分析報告】
    print("\n" + "=" * 45)
    print("📊 【統計與稽核分析報告】")
    print("=" * 45)
    print(f"🔹 總共偵測到的球標實體   : {len(raw_balloons)} 個")
    print(f"🔹 識別到的範圍型球標     : {len(range_pairs)} 組")
    print(f"🔹 實際涵蓋的總球標範圍   : 1 ~ {max_id}")
    
    if all_duplicates:
        print(f"\n⚠️ 【警告】發現重複出現或被範圍重疊涵蓋的球標號碼: {all_duplicates}")
    else:
        print("\n✅ 無重複的單一或涵蓋球標。")

    if missing_ids:
        print(f"⚠️ 【警告】發現缺號/遺失的球標 (1 ~ {max_id}):\n{missing_ids}")
    else:
        print("✅ 無缺號現象，所有號碼皆完整涵蓋。")
    print("==========================================")
    
    if OUTPUT_CSV:
        if all_duplicates:
            fid.write(f"\n【警告】發現重複出現或被範圍重疊涵蓋的球標號碼: {all_duplicates}\n")
        else:
            fid.write("\n無重複的單一或涵蓋球標。")

        if missing_ids:
            fid.write(f"【警告】發現缺號/遺失的球標 (1 ~ {max_id}):{missing_ids}\n")
        else:
            fid.write("無缺號現象，所有號碼皆完整涵蓋。")
        fid.close()

if __name__ == '__main__':
    config = load_config('config.ini')
    if config:
        target_dxf = 'test.dxf'
        if os.path.exists(target_dxf):
            audit_file(target_dxf, config)
