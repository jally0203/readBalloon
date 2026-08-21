import ezdxf

doc = ezdxf.readfile("test.txt")
msp = doc.modelspace()

print("🔍 開始在 test.txt 中深層搜尋 '360' 或 '360.20'...\n")

# 1. 搜尋 ModelSpace TEXT / MTEXT
found_count = 0
for entity in msp:
    dxftype = entity.dxftype()
    if dxftype in ('TEXT', 'MTEXT'):
        text = entity.plain_text() if dxftype == 'MTEXT' else entity.dxf.text
        if '360' in text:
            pos = entity.dxf.insert
            print(f"📌 [ModelSpace {dxftype}] 內容: '{text}' | 位置: X={pos.x:.2f}, Y={pos.y:.2f}")
            found_count += 1

# 2. 搜尋 Blocks / DIMENSION 匿名圖塊
for block in doc.blocks:
    for entity in block:
        if entity.dxftype() in ('TEXT', 'MTEXT'):
            text = entity.plain_text() if entity.dxftype() == 'MTEXT' else entity.dxf.text
            if '360' in text:
                pos = entity.dxf.insert
                print(f"📌 [Block: {block.name} {entity.dxftype()}] 內容: '{text}' | 本地位置: X={pos.x:.2f}, Y={pos.y:.2f}")
                found_count += 1

# 3. 搜尋 DIMENSION 標註實體
for dim in msp.query('DIMENSION'):
    text = dim.dxf.text if dim.dxf.hasattr('text') else ""
    meas = dim.dxf.actual_measurement if dim.dxf.hasattr('actual_measurement') else None
    if '360' in text or (meas and abs(meas - 360.20) < 0.1):
        pos = dim.dxf.defpoint if dim.dxf.hasattr('defpoint') else (0,0,0)
        print(f"📌 [DIMENSION 實體] 文字: '{text}' | 實測值: {meas} | 位置: X={pos.x:.2f}, Y={pos.y:.2f}")
        found_count += 1

if found_count == 0:
    print("❌ 完全沒找到含有 '360' 的文字實體！可能被炸成 LINE/POLYLINE 線條（Exploded Text）了。")
