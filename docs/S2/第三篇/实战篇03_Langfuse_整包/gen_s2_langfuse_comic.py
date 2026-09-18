#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""番外篇 · 漫画风贴图 v2（漫说测试）：
   字号加大 · 气泡重做 · 内容铺满版面
   - 10 张竖版贴图（1080x1920，sticker-s2xc-01..10）
   - 1 张横版封面（1880x800，cover-s2xc-01）
字体：ZCOOL KuaiLe（站酷快乐体） 渲染：rsvg-convert
"""
import os, subprocess

OUT = os.path.expanduser("~/.openclaw/workspace/session-files/01M20S67DZSWEWWHNP370TWZVB/agent-testing-series/figs")
os.makedirs(OUT, exist_ok=True)

W, H = 1080, 1920
MX, CW = 60, 960
INK = "#1F1B16"
PAPER = "#FFF6E5"
WHT = "#FFFFFF"
YEL = "#FFD93D"
RED = "#FF6B6B"
BLU = "#4D8BFF"
GRN = "#3FBF63"
PUR = "#9B5DFF"
SKIN = "#FFE0B2"
FONT = "ZCOOL KuaiLe, Noto Sans CJK SC"

# 字号基线（v2 全面加大）
F_H1 = 96      # 主标题
F_H2 = 64      # 副标题
F_CHAP = 44    # 话数标签
F_BUB = 46     # 气泡正文
F_CT = 48      # 卡片标题
F_CB = 38      # 卡片正文
F_CS = 32      # 卡片小字
F_LEAD = 60    # 金句


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def T(x, y, s, size, fill=INK, anchor="start", rot=None, sw=0, swc=INK, sp=0):
    tr = f' transform="rotate({rot} {x} {y})"' if rot else ''
    st = f' stroke="{swc}" stroke-width="{sw}" paint-order="stroke"' if sw else ''
    ls = f' letter-spacing="{sp}"' if sp else ''
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" text-anchor="{anchor}"'
            f' font-family="{FONT}"{tr}{st}{ls}>{esc(s)}</text>')


def panel(x, y, w, h, fill=WHT, sw=7, rot=None, dash=None):
    tr = f' transform="rotate({rot} {x+w/2} {y+h/2})"' if rot else ''
    d = f' stroke-dasharray="{dash}"' if dash else ''
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="30" fill="{fill}"'
            f' stroke="{INK}" stroke-width="{sw}"{d}{tr}/>')


def card(y, h, fill=WHT, x=MX, w=CW, sw=7):
    return panel(x, y, w, h, fill, sw)


def bubble(x, y, w, h, lines, size=F_BUB, tail="bl", fill=WHT, lh=None):
    """对话气泡 v2：单条干净尾巴 + 更宽内边距"""
    lh = lh or int(size * 1.46)
    s = panel(x, y, w, h, fill, 7)
    pad = 46
    if tail == "bl":
        bx0, bx1 = x + 52, x + 168
        s += (f'<path d="M {bx0} {y+h-10} L {bx0+10} {y+h+66} L {bx1} {y+h-10} Z" fill="{fill}"'
              f' stroke="{INK}" stroke-width="7" stroke-linejoin="round"/>'
              f'<rect x="{bx0+8}" y="{y+h-16}" width="{bx1-bx0-16}" height="12" fill="{fill}"/>')
    elif tail == "br":
        bx0, bx1 = x + w - 168, x + w - 52
        s += (f'<path d="M {bx0} {y+h-10} L {bx1-10} {y+h+66} L {bx1} {y+h-10} Z" fill="{fill}"'
              f' stroke="{INK}" stroke-width="7" stroke-linejoin="round"/>'
              f'<rect x="{bx0+8}" y="{y+h-16}" width="{bx1-bx0-16}" height="12" fill="{fill}"/>')
    elif tail == "tr":
        bx0, bx1 = x + w - 190, x + w - 60
        s += (f'<path d="M {bx0} {y+10} L {bx1-6} {y-64} L {bx1} {y+10} Z" fill="{fill}"'
              f' stroke="{INK}" stroke-width="7" stroke-linejoin="round"/>'
              f'<rect x="{bx0+8}" y="{y+4}" width="{bx1-bx0-16}" height="12" fill="{fill}"/>')
    cy = y + pad + int(size * 0.82)
    for ln in lines:
        s += T(x + pad, cy, ln, size)
        cy += lh
    return s


def cloud(x, y, w, h, lines, size=38, lh=54):
    s = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h//2}" fill="{WHT}"'
         f' stroke="{INK}" stroke-width="6" stroke-dasharray="16 11"/>')
    s += f'<circle cx="{x+46}" cy="{y+h+34}" r="16" fill="{WHT}" stroke="{INK}" stroke-width="6"/>'
    s += f'<circle cx="{x+18}" cy="{y+h+72}" r="10" fill="{WHT}" stroke="{INK}" stroke-width="6"/>'
    cy = y + 62
    for ln in lines:
        s += T(x + 44, cy, ln, size)
        cy += lh
    return s


def sfx(x, y, text, size=64, rot=-14, col=RED, sw=4):
    return T(x, y, text, size, col, rot=rot, sw=sw, swc=INK)


def badge(x, y, text, fill=YEL, size=36, pad=40, h=68, anchor="start"):
    w = int(len(text) * size * 0.96 + pad * 2)
    if anchor == "middle":
        x = x - w // 2
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h//2}" fill="{fill}" stroke="{INK}" stroke-width="6"/>'
            + T(x + w // 2, y + h // 2 + size // 3, text, size, INK, anchor="middle"))


def mascot(cx, cy, s=1.0, mood="happy", clothes=BLU):
    """小测试员（v2：线条加粗）"""
    g = [f'<g transform="translate({cx} {cy}) scale({s})">']
    g.append(f'<rect x="-46" y="150" width="32" height="88" rx="15" fill="#3B4A6B" stroke="{INK}" stroke-width="7"/>')
    g.append(f'<rect x="14" y="150" width="32" height="88" rx="15" fill="#3B4A6B" stroke="{INK}" stroke-width="7"/>')
    g.append(f'<rect x="-70" y="52" width="140" height="112" rx="34" fill="{clothes}" stroke="{INK}" stroke-width="7"/>')
    al = '-120,116 -86,84' if mood in ("yeah", "happy") else '-126,96 -84,120'
    g.append(f'<polyline points="{al}" fill="none" stroke="{INK}" stroke-width="8" stroke-linecap="round"/>')
    g.append(f'<polyline points="86,84 120,116" fill="none" stroke="{INK}" stroke-width="8" stroke-linecap="round"/>')
    g.append(f'<circle cx="-128" cy="{80 if mood in ("yeah","happy") else 92}" r="21" fill="{SKIN}" stroke="{INK}" stroke-width="7"/>')
    g.append(f'<circle cx="128" cy="92" r="21" fill="{SKIN}" stroke="{INK}" stroke-width="7"/>')
    g.append(f'<circle cx="0" cy="-6" r="80" fill="{SKIN}" stroke="{INK}" stroke-width="7"/>')
    g.append(f'<path d="M -80 -22 A 80 80 0 0 1 80 -22 Q 42 -76 0 -68 Q -42 -76 -80 -22 Z" fill="{INK}"/>')
    if mood == "cool":
        g.append(f'<rect x="-60" y="-32" width="48" height="28" rx="9" fill="{INK}"/>')
        g.append(f'<rect x="12" y="-32" width="48" height="28" rx="9" fill="{INK}"/>')
        g.append(f'<path d="M -60 -32 L -12 -32 M 12 -32 L 60 -32" stroke="{INK}" stroke-width="7"/>')
    elif mood == "shock":
        g.append(f'<circle cx="-27" cy="-14" r="14" fill="{WHT}" stroke="{INK}" stroke-width="6"/>')
        g.append(f'<circle cx="27" cy="-14" r="14" fill="{WHT}" stroke="{INK}" stroke-width="6"/>')
        g.append(f'<circle cx="-27" cy="-14" r="6" fill="{INK}"/>')
        g.append(f'<circle cx="27" cy="-14" r="6" fill="{INK}"/>')
    else:
        g.append(f'<circle cx="-27" cy="-14" r="10" fill="{INK}"/>')
        g.append(f'<circle cx="27" cy="-14" r="10" fill="{INK}"/>')
        g.append(f'<circle cx="-24" cy="-17" r="3.4" fill="{WHT}"/>')
        g.append(f'<circle cx="30" cy="-17" r="3.4" fill="{WHT}"/>')
    g.append(f'<ellipse cx="-52" cy="16" rx="16" ry="10" fill="{RED}" opacity="0.5"/>')
    g.append(f'<ellipse cx="52" cy="16" rx="16" ry="10" fill="{RED}" opacity="0.5"/>')
    if mood == "shock":
        g.append(f'<ellipse cx="0" cy="38" rx="18" ry="22" fill="{INK}"/>')
    elif mood == "sweat":
        g.append(f'<path d="M -26 40 q 13 13 26 0 q 13 -13 26 0" fill="none" stroke="{INK}" stroke-width="7"/>')
    elif mood == "think":
        g.append(f'<path d="M -22 40 q 22 9 44 -2" fill="none" stroke="{INK}" stroke-width="7"/>')
    elif mood == "cool":
        g.append(f'<path d="M -28 36 q 28 17 56 -7" fill="none" stroke="{INK}" stroke-width="7"/>')
    else:
        g.append(f'<path d="M -30 32 q 30 36 60 0" fill="none" stroke="{INK}" stroke-width="8"/>')
    if mood == "sweat":
        g.append(f'<path d="M 70 -50 q 15 24 0 32 q -15 -8 0 -32 Z" fill="{BLU}" stroke="{INK}" stroke-width="5"/>')
    g.append('</g>')
    return "".join(g)


def head(n):
    return (f'<rect x="0" y="0" width="{W}" height="100" fill="{YEL}"/>'
            f'<line x1="0" y1="100" x2="{W}" y2="100" stroke="{INK}" stroke-width="7"/>'
            + T(36, 68, "漫说测试 · 实战篇 03", 36)
            + T(W - 36, 68, f"{n}/10", 38, anchor="end"))


def wmc():
    return (f'<rect x="{(W-400)//2}" y="1830" width="400" height="62" rx="31" fill="{WHT}" stroke="{INK}" stroke-width="6"/>'
            + T(W // 2, 1874, "Python测试之道", 34, anchor="middle"))


def build(elems, w=W, h=H):
    defs = (f'<defs><pattern id="dots" width="28" height="28" patternUnits="userSpaceOnUse">'
            f'<circle cx="5" cy="5" r="2.6" fill="{INK}" opacity="0.09"/></pattern></defs>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'font-family="{FONT}">' + defs + f'<rect width="{w}" height="{h}" fill="{PAPER}"/>'
            f'<rect width="{w}" height="{h}" fill="url(#dots)"/>' + "".join(elems) + "</svg>")


def save(name, svg, w=W, h=H):
    ps = os.path.join(OUT, f"{name}-src.svg")
    pp = os.path.join(OUT, f"{name}.png")
    open(ps, "w", encoding="utf-8").write(svg)
    subprocess.run(["rsvg-convert", ps, "-o", pp], check=True)
    print("saved", pp)


def kv(y, items, h=None, fill=WHT, size=F_CB, lh=64, title=None, tcol=INK):
    """按行铺满的卡片：items=[(标签, 值)]；返回 (svg, 卡片高度)"""
    n = len(items)
    hh = h or (150 + lh * n if title else 120 + lh * n)
    s = card(y, hh, fill)
    cy = y + 78
    if title:
        s += T(MX + 44, cy, title, F_CT, tcol)
        cy += 76
    for a, b in items:
        s += f'<circle cx="{MX+62}" cy="{cy-14}" r="15" fill="{GRN}" stroke="{INK}" stroke-width="5"/>'
        s += T(MX + 100, cy, a, size)
        if b:
            s += T(MX + CW - 44, cy, b, int(size * 0.72), "#6B6257", anchor="end")
        cy += lh
    return s, hh



# ============================================================ Langfuse 篇：10 张贴图
P = []

# ---- 1 封面 ----
e = [head(1)]
e.append(badge(W // 2, 150, "漫说测试 · 实战篇 03", YEL, 42, anchor="middle"))
e.append(T(W // 2, 330, "打开 Agent", F_H1, INK, anchor="middle"))
e.append(T(W // 2, 470, "黑匣子", 100, RED, anchor="middle", sw=4))
e.append(bubble(70, 550, 620, 200, ["评测只说", "“过没过”…"], 46, "bl"))
e.append(mascot(820, 900, 1.16, "happy"))
e.append(card(1120, 340, WHT))
e.append(T(MX + 44, 1210, "评测 = 守门员", F_CT))
e.append(T(MX + 44, 1300, "追踪 = 行车记录仪", F_CT, BLU))
e.append(T(MX + 44, 1390, "一个问质量，一个问过程", F_CS, "#6B6257"))
e.append(card(1500, 300, YEL))
e.append(T(MX + 44, 1590, "Langfuse 轨迹追踪实战", 46))
e.append(T(MX + 44, 1680, "不改业务代码 · 没配就零影响", 36))
e.append(T(MX + 44, 1750, "全套 9 话 · 读完约 4 分钟", 30, "#6B5744"))
e.append(wmc())
P.append(build(e))

# ---- 2 两个问题 ----
e = [head(2)]
e.append(T(MX, 190, "第 1 话 · 两个不同的问题", F_CHAP, "#6B6257"))
e.append(mascot(200, 440, 0.82, "think"))
e.append(bubble(410, 270, 610, 190, ["评测：这次", "过没过？"], 46, "bl"))
e.append(bubble(410, 530, 610, 190, ["追踪：到底", "发生了什么？"], 46, "bl", fill="#EAF3FF"))
e.append(card(790, 380, WHT))
e.append(T(MX + 44, 880, "评测 = 守门员", F_CT))
e.append(T(MX + 100, 962, "只守你安排他守的那几脚球", 36))
e.append(T(MX + 44, 1070, "追踪 = 行车记录仪", F_CT, BLU))
e.append(T(MX + 100, 1150, "出事后唯一能回看现场的东西", 36))
e.append(card(1200, 300, "#FFF3F3"))
e.append(T(MX + 44, 1290, "只评测 → 漏掉没写用例的场景", 38))
e.append(T(MX + 44, 1380, "只追踪 → 没有“通过线”", 38, RED))
e.append(card(1530, 260, "#EAF7EE"))
e.append(T(MX + 44, 1620, "两个都要，缺一不可", 42, "#2F7A45"))
e.append(T(MX + 44, 1704, "评测守住底线，追踪看见真相", 34, "#4F6B57"))
e.append(wmc())
P.append(build(e))

# ---- 3 三个概念 ----
e = [head(3)]
e.append(T(MX, 190, "第 2 话 · 三个概念", F_CHAP, "#6B6257"))
e.append(card(250, 400, WHT))
e.append(T(MX + 44, 350, "Trace · 一次会话", F_CT, BLU))
e.append(T(MX + 44, 440, "你问一句、它答一句", 36))
e.append(T(MX + 44, 520, "整条链路算一条 Trace", 36))
e.append(T(MX + 44, 596, "→ thread_id 映射成 session", F_CS, "#6B6257"))
e.append(card(680, 400, WHT))
e.append(T(MX + 44, 780, "Span · 一次运行步骤", F_CT, GRN))
e.append(T(MX + 44, 870, "主管 → 子 Agent → 工具", 36))
e.append(T(MX + 44, 950, "层层嵌套，构成调用树", 36))
e.append(T(MX + 44, 1026, "→ 这棵树就是行车轨迹", F_CS, "#6B6257"))
e.append(card(1110, 400, WHT))
e.append(T(MX + 44, 1210, "Generation · 一次模型调用", F_CT, PUR))
e.append(T(MX + 44, 1300, "额外记录 token / 成本 / 模型名", 36))
e.append(T(MX + 44, 1380, "还有完整 prompt 与输出", 36))
e.append(T(MX + 44, 1456, "→ 钱花在哪，一目了然", F_CS, "#6B6257"))
e.append(card(1540, 250, YEL))
e.append(T(MX + 44, 1630, "有这三层，才答得了", 40))
e.append(T(MX + 44, 1710, "“评测答不了”的那些问题", 40, RED))
e.append(wmc())
P.append(build(e))

# ---- 4 接入三步 ----
e = [head(4)]
e.append(T(MX, 190, "第 3 话 · 接入三步", F_CHAP, "#6B6257"))
e.append(card(250, 330, WHT))
e.append(badge(MX + 44, 285, "①", GRN, 40))
e.append(T(MX + 190, 375, "装依赖 + 配 key", F_CT))
e.append(T(MX + 160, 448, "langfuse>=4.0.0", 34, "#6B6257"))
e.append(T(MX + 160, 516, "LANGFUSE_PUBLIC_KEY / SECRET_KEY", 30, "#6B6257"))
e.append(card(610, 330, WHT))
e.append(badge(MX + 44, 645, "②", GRN, 40))
e.append(T(MX + 190, 735, "加 observability 模块", F_CT))
e.append(T(MX + 160, 808, "管开关 / 采样 / 脱敏 / 回调", 34, "#6B6257"))
e.append(T(MX + 160, 876, "业务代码一行都不用改", 34, "#6B6257"))
e.append(card(970, 330, WHT))
e.append(badge(MX + 44, 1005, "③", GRN, 40))
e.append(T(MX + 190, 1095, "把回调挂到运行配置", F_CT))
e.append(T(MX + 160, 1168, "self._attach_tracing(config, …)", 30, "#6B6257"))
e.append(T(MX + 160, 1236, "就这么一行", 34, RED))
e.append(card(1330, 430, "#0F172A"))
e.append(T(MX + 44, 1420, "config = self._attach_tracing(", 32, "#9BE7B0"))
e.append(T(MX + 84, 1480, "self._build_config(thread_id),", 32, "#9BE7B0"))
e.append(T(MX + 84, 1540, "thread_id=thread_id,", 32, "#9BE7B0"))
e.append(T(MX + 84, 1600, "context=context,", 32, "#9BE7B0"))
e.append(T(MX + 44, 1660, ")", 32, "#9BE7B0"))
e.append(T(MX + 44, 1720, "# 未启用 → 原样返回，零开销", 30, YEL))
e.append(wmc())
P.append(build(e))

# ---- 5 零侵入 ----
e = [head(5)]
e.append(T(MX, 190, "第 4 话 · 最要紧的设计", F_CHAP, "#6B6257"))
e.append(mascot(210, 450, 0.84, "cool"))
e.append(bubble(430, 280, 590, 200, ["没配 key", "就是 no-op"], 46, "bl"))
e.append(card(800, 330, WHT))
e.append(T(MX + 44, 890, "未启用追踪时", F_CT))
e.append(T(MX + 44, 980, "连回调对象都不创建", 38))
e.append(T(MX + 44, 1060, "彻底零开销，行为逐字节一致", 34, "#6B6257"))
e.append(card(1170, 330, "#EAF7EE"))
e.append(T(MX + 44, 1260, "这条被回归测试守住了", F_CT, "#2F7A45"))
e.append(T(MX + 44, 1350, "pytest tests -m \"not integration\"", 32, "#4F6B57"))
e.append(T(MX + 44, 1430, "→ 176 passed", 44, GRN))
e.append(card(1540, 250, YEL))
e.append(T(MX + 44, 1630, "改造的前提是：不破坏基线", 40))
e.append(T(MX + 44, 1714, "否则你连“有没有变坏”都不知道", 32, "#6B5744"))
e.append(wmc())
P.append(build(e))

# ---- 6 打开黑匣子 ----
e = [head(6)]
e.append(T(MX, 190, "第 5 话 · 打开黑匣子", F_CHAP, "#6B6257"))
e.append(card(250, 640, "#0F172A"))
e.append(T(MX + 40, 340, "session: eval-8f3c  [mode:subagents]", 30, YEL))
e.append(T(MX + 40, 410, "agent-subagents          11.2s", 30, "#C9D4E8"))
e.append(T(MX + 80, 480, "supervisor            3.1s", 30, "#9BE7B0"))
e.append(T(MX + 120, 550, "sql_specialist       6.8s", 30, "#9BE7B0"))
e.append(T(MX + 160, 620, "sql_db_list_tables   0.3s", 30, "#9BE7B0"))
e.append(T(MX + 160, 690, "sql_db_schema        0.4s", 30, "#9BE7B0"))
e.append(T(MX + 160, 760, "sql_db_query_checker 2.1s", 30, RED))
e.append(T(MX + 160, 830, "sql_db_query         0.2s", 30, GRN))
e.append(card(930, 420, WHT))
e.append(T(MX + 44, 1020, "第一次看到这棵树", F_CT))
e.append(T(MX + 44, 1110, "有点震撼：一次“查询”", 38))
e.append(T(MX + 44, 1190, "背后这么多步", 38, RED))
e.append(T(MX + 44, 1270, "而你的直觉经常是错的", F_CS, "#6B6257"))
e.append(card(1390, 380, "#EAF3FF"))
e.append(T(MX + 44, 1480, "时间花在哪？", F_CT, BLU))
e.append(T(MX + 44, 1570, "模型思考 5.2s ＞ 查数据 0.2s", 38))
e.append(T(MX + 44, 1650, "事实和直觉，常常相反", 34, "#6B6257"))
e.append(wmc())
P.append(build(e))

# ---- 7 场景一：慢在哪 ----
e = [head(7)]
e.append(T(MX, 190, "第 6 话 · 用起来 ① 慢在哪", F_CHAP, "#6B6257"))
e.append(mascot(200, 450, 0.8, "shock"))
e.append(bubble(410, 280, 610, 200, ["用户说：你这个", "Agent 好慢啊"], 42, "bl"))
e.append(card(790, 400, "#FFF3F3", x=MX, w=CW))
e.append(T(MX + 44, 900, "以前：只能猜", 40, "#6B6257"))
e.append(T(MX + 44, 990, "现在：87% 时间在两次模型调用", 38, RED))
e.append(T(MX + 44, 1070, "SQL 查询只占 0.2 秒", 38))
e.append(card(1220, 330, "#EAF7EE"))
e.append(T(MX + 44, 1320, "优化方向立刻明确了", F_CT, "#2F7A45"))
e.append(T(MX + 44, 1410, "能不能省掉 query_checker？", 36))
e.append(T(MX + 44, 1490, "能不能换更小的模型？", 36))
e.append(card(1590, 200, WHT))
e.append(T(MX + 44, 1710, "而不是盲目去优化数据库", 40, "#6B6257"))
e.append(wmc())
P.append(build(e))

# ---- 8 场景二：错在哪一步 ----
e = [head(8)]
e.append(T(MX, 190, "第 7 话 · 用起来 ② 错在哪步", F_CHAP, "#6B6257"))
e.append(panel(60, 250, 460, 560, "#EAF7EE"))
e.append(T(290, 330, "正常轨迹", 42, "#2F7A45", anchor="middle"))
for i, ln in enumerate(["list_tables  ✓", "db_schema   ✓", "sql_db_query ✓", "→ [(3,)]"]):
    e.append(T(100, 410 + i * 92, ln, 34, "#2F7A45"))
e.append(panel(560, 250, 460, 560, "#FFF3F3"))
e.append(T(790, 330, "异常轨迹", 42, RED, anchor="middle"))
for i, ln in enumerate(["list_tables  ✓", "db_schema   ✓", "直接作答     ✗", "→ 编造答案"]):
    e.append(T(600, 410 + i * 92, ln, 34, RED))
e.append(card(860, 300, WHT))
e.append(T(MX + 44, 960, "差异点在第 3 步", F_CT))
e.append(T(MX + 44, 1050, "模型跳过了查询，直接作答", 38, RED))
e.append(card(1190, 300, YEL))
e.append(T(MX + 44, 1290, "评测只会说：这条没过", 40))
e.append(T(MX + 44, 1380, "追踪会说：它在哪抄了近道", 40, INK))
e.append(card(1520, 270, "#EAF3FF"))
e.append(T(MX + 44, 1620, "上次那个偶发缺陷", 38, BLU))
e.append(T(MX + 44, 1704, "有追踪只要两分钟", 38, BLU))
e.append(wmc())
P.append(build(e))

# ---- 9 场景三：闭环 ----
e = [head(9)]
e.append(T(MX, 190, "第 8 话 · 用起来 ③ 闭环", F_CHAP, "#6B6257"))
e.append(card(250, 200, WHT))
e.append(T(MX + 44, 380, "① 线上真实流量", F_CT))
e.append(card(490, 200, WHT))
e.append(T(MX + 44, 620, "② 追踪全程记录", F_CT))
e.append(card(730, 200, WHT))
e.append(T(MX + 44, 860, "③ 筛出“烂 case”", F_CT))
e.append(card(970, 200, "#EAF7EE"))
e.append(T(MX + 44, 1100, "④ 复现成评测用例", F_CT, "#2F7A45"))
e.append(card(1250, 300, YEL))
e.append(T(MX + 44, 1350, "评测集不该拍脑袋造", 42))
e.append(T(MX + 44, 1440, "应该从真实轨迹里“长”出来", 42, RED))
e.append(card(1590, 230, "#EAF3FF"))
e.append(T(MX + 44, 1700, "跑一周筛 20 条烂 case", 36, BLU))
e.append(T(MX + 44, 1774, "胜过闭门造 200 条", 36, BLU))
e.append(wmc())
P.append(build(e))

# ---- 10 四个坑 + CTA ----
e = [head(10)]
e.append(T(MX, 190, "第 9 话 · 四个坑", F_CHAP, "#6B6257"))
keng = [("忘 flush", "脚本跑完就退出 → 平台一片空白", RED),
        ("采样太狠", "想复盘的坏 case 被采样掉", PUR),
        ("密钥进平台", "prompt 带 key / 手机号 → 泄露", BLU),
        ("以为不追踪不耗", "回调本身也有开销 → 提前拦住", GRN)]
for i, (a, b, col) in enumerate(keng):
    y = 250 + i * 250
    e.append(card(y, 210, WHT))
    e.append(f'<circle cx="{MX+72}" cy="{y+105}" r="40" fill="{col}" stroke="{INK}" stroke-width="6"/>')
    e.append(T(MX + 72, y + 122, "✕", 48, WHT, anchor="middle"))
    e.append(T(MX + 150, y + 92, a, 44))
    e.append(T(MX + 150, y + 164, b, 32, "#6B6257"))
e.append(mascot(220, 1420, 0.62, "yeah"))
e.append(bubble(430, 1290, 590, 190, ["评测守底线", "追踪看真相"], 42, "bl"))
e.append(card(1560, 270, "#EAF3FF"))
e.append(T(MX + 44, 1660, "源码 + 改造 patch 免费领", 38, BLU))
e.append(T(MX + 44, 1740, "后台回复「agent」", 38, BLU))
e.append(wmc())
P.append(build(e))

for i, svg in enumerate(P, 1):
    save(f"sticker-s2l-{i:02d}", svg)

# ============================================================ 漫画风横版封面
CW2, CH2 = 1880, 800
e = [f'<rect width="{CW2}" height="{CH2}" fill="{PAPER}"/>',
     f'<rect width="{CW2}" height="{CH2}" fill="url(#dots)"/>']
e.append(f'<rect x="0" y="0" width="{CW2}" height="16" fill="{BLU}"/>')
e.append(badge(90, 60, "漫说测试 · 实战篇 03", YEL, 40))
e.append(T(90, 310, "打开 Agent 黑匣子", 96, INK))
e.append(T(90, 430, "Langfuse 轨迹追踪实战", 74, BLU, sw=3))
e.append(T(90, 520, "评测是守门员，追踪是行车记录仪 · 不改业务代码", 40, "#6B6257"))
e.append(mascot(1530, 370, 1.0, "cool"))
e.append(bubble(1140, 570, 650, 170, ["有追踪，不怕意外"], 44, "none"))
e.append(T(90, 660, "公众号：Python测试之道    ·    源码领取：后台回复「agent」", 38, INK))
e.append(sfx(1010, 235, "叮", 64, -12, GRN))
save("cover-s2l-01", build(e, CW2, CH2), CW2, CH2)
print("all done")
