# -*- coding: utf-8 -*-
"""评委打分系统 · 完整回归测试

用法：
    cd D:\AIWorkspaces\评委打分
    $env:PYTHONIOENCODING="utf-8"
    $env:PLAYWRIGHT_BROWSERS_PATH="0"
    & 'D:\AIWorkspaces\douyin-knowledge-mcp\.venv\Scripts\python.exe' 测试脚本\test_all.py

依赖：Playwright（借用 douyin 项目的 venv）
"""
import os
import sys
import json
import tempfile
import re
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("缺少 playwright，请用 douyin 项目的 venv：")
    print(r"  D:\AIWorkspaces\douyin-knowledge-mcp\.venv\Scripts\python.exe")
    sys.exit(1)

# 被测文件（可传参覆盖）
BASE = Path(__file__).resolve().parent.parent
DEFAULT_FILE = BASE / "dist" / "example.html"
TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FILE
URL = TARGET.as_uri()

R = []
def ck(name, ok, detail=""):
    R.append((name, ok, detail))
    print(f"   {'✅' if ok else '❌'} {name}" + (f"   [{detail}]" if detail else ""))

def section(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main():
    print(f"被测文件: {TARGET}")
    print(f"存在: {TARGET.exists()}")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1500, "height": 1100},
                                  accept_downloads=True,
                                  permissions=["clipboard-read", "clipboard-write"])
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

        pg.goto(URL)
        pg.wait_for_timeout(800)
        pg.evaluate("() => localStorage.clear()")
        pg.reload()
        pg.wait_for_timeout(900)

        # ============ 1. 页面加载 ============
        section("【1】页面加载")
        ck("页面能打开", pg.title() != "", pg.title()[:40])
        ck("表格可见", pg.evaluate("() => getComputedStyle(document.getElementById('tableWrap')).display") != 'none')
        ck("标题栏存在", pg.is_visible("#titleBar"))
        rows = pg.evaluate("() => state.rows.length")
        ck("至少有 20 行", rows >= 20, str(rows))

        # ============ 2. 分数换算 ============
        section("【2】分数换算（核心）")
        cases = [
            ('928', 10, 2, 9.28),
            ('1000', 10, 2, 10.0),
            ('85', 10, 2, 0.85),
            ('9.5', 10, 2, 9.5),
            ('9850', 100, 2, 98.5),
            ('95', 10, 0, 95),
            ('9285', 10, 3, 9.285),
        ]
        for raw, mx, dec, exp in cases:
            got = pg.evaluate("([r,m,d]) => parseScore(r,m,d)", [raw, mx, dec])
            ok = got is not None and abs(got - exp) < 1e-9
            ck(f"'{raw}' ({mx}分/{dec}位) → {exp}", ok, f"实得 {got}")

        # ============ 3. 平均分与名次 ============
        section("【3】平均分与名次")
        pg.evaluate("""() => {
            state.maxScore=10; state.decimals=2; state.judgeCount=5;
            state.dropHighLow=false; state.awards={first:0,second:0,third:0};
            state.rows=[];
            state.rows.push({id:'a',no:1,name:'A',actor:'',unit:'',scores:['928','850','900','880','950']});
            state.rows.push({id:'b',no:2,name:'B',actor:'',unit:'',scores:['700','750','800','700','750']});
            state.rows.push({id:'c',no:3,name:'C',actor:'',unit:'',scores:['1000','900','950','1000','900']});
            for(let i=4;i<=20;i++) state.rows.push(makeEmptyRow(i));
            save(); renderHead(); renderBody();
        }""")
        pg.wait_for_timeout(300)
        calc = pg.evaluate("""() => state.rows.slice(0,3).map(r => calcRow(r).avg)""")
        ck("A 平均 9.016", abs(calc[0] - 9.016) < 1e-6, f"{calc[0]:.4f}")
        ck("B 平均 7.4", abs(calc[1] - 7.4) < 1e-6, f"{calc[1]:.4f}")
        ck("C 平均 9.5", abs(calc[2] - 9.5) < 1e-6, f"{calc[2]:.4f}")
        ranks = pg.evaluate("""() => {
            const rm = computeRanks().rankMap;
            return state.rows.slice(0,3).map(r => rm[r.id]);
        }""")
        ck("名次 C=1 A=2 B=3", ranks == [2, 3, 1], str(ranks))

        # ============ 4. 去最高最低 ============
        section("【4】去掉一个最高分和一个最低分")
        pg.evaluate("""() => {
            state.rows[0].scores = ['928','850','900','880','950'];
            state.dropHighLow = true;
            save(); renderBody();
        }""")
        pg.wait_for_timeout(250)
        drop = pg.evaluate("""() => {
            const s = calcRow(state.rows[0]);
            return {avg: s.avg, dropped: s.dropped, count: s.count};
        }""")
        exp_avg = (9.28 + 9.00 + 8.80) / 3
        ck("去掉后平均正确", abs(drop['avg'] - exp_avg) < 1e-6, f"{drop['avg']:.4f} 期望 {exp_avg:.4f}")
        ck("去掉的格子不重复", len(set(drop['dropped'])) == 2, str(drop['dropped']))
        ck("参与计算 3 个", drop['count'] == 3, str(drop['count']))

        # ============ 5. 同分并列 ============
        section("【5】同分并列")
        tie = pg.evaluate("""() => {
            state.rows[0].scores = {0:8,1:8,2:8,3:8,4:8};
            state.rows[1].scores = {0:8,1:8,2:8,3:8,4:8};
            state.dropHighLow = false;
            save(); renderBody();
            const rm = computeRanks().rankMap;
            return [rm[state.rows[0].id], rm[state.rows[1].id]];
        }""")
        ck("同分并列同名次", tie[0] == tie[1], str(tie))

        # ============ 6. 导入分隔符 ============
        section("【6】导入分隔符兼容")
        seps = [
            ("制表符", "节目A\t张三\n节目B\t李四"),
            ("中文逗号", "节目C，王五\n节目D，赵六"),
            ("顿号", "节目E、孙七"),
            ("竖线", "节目F | 周八"),
            ("分号", "节目G;吴九"),
            ("多空格", "节目H    郑十"),
        ]
        for label, text in seps:
            pg.evaluate("""() => {
                state.rows=[]; for(let i=1;i<=20;i++) state.rows.push(makeEmptyRow(i));
                save(); renderBody();
            }""")
            pg.wait_for_timeout(150)
            pg.fill("#importBox", text)
            pg.click('button:has-text("导入到表格")')
            pg.wait_for_timeout(250)
            got = pg.evaluate("() => state.rows.slice(0,2).map(r => r.name + '|' + r.actor)")
            ck(f"{label} 导入", got[0].startswith('节目'), str(got[0]))

        # ============ 7. 导出列勾选 ============
        section("【7】导出列勾选")
        pg.evaluate("""() => {
            state.rows[0].scores=['928','950','900','880','935'];
            document.querySelectorAll('.exp-col').forEach(b => {
                b.checked = (b.dataset.col==='no'||b.dataset.col==='name'||b.dataset.col==='avg'||b.dataset.col==='rank');
            });
            onExportColsChange();
            save(); renderBody();
        }""")
        pg.wait_for_timeout(300)
        try:
            with pg.expect_download(timeout=8000) as dl:
                pg.click('button:has-text("导出 Excel")')
            tmp = os.path.join(tempfile.gettempdir(), 'test_export.xls')
            dl.value.save_as(tmp)
            html = open(tmp, encoding='utf-8-sig').read()
            heads = re.findall(r'<th>([^<]+)</th>', html)
            # 勾选「平均分」时，若开启了分数修正，会自动带出「分数修正」「最终成绩」两列
            expect_cols = 4 + (2 if pg.evaluate("() => state.showAdjust") else 0)
            ck("按勾选导出列数", len(heads) == expect_cols, f"{len(heads)} 列: {heads}")
            ck("含序号/节目名称/平均分/名次",
               all(h in heads for h in ['序号','节目名称','平均分','名次']), str(heads))
            if pg.evaluate("() => state.showAdjust"):
                ck("含分数修正/最终成绩", '分数修正' in heads and '最终成绩' in heads, str(heads))
        except Exception as e:
            ck("导出 Excel", False, str(e)[:60])

        # ============ 8. 数据持久化 ============
        section("【8】数据持久化")
        pg.evaluate("""() => {
            state.rows[0].name = '持久化测试';
            state.rows[0].scores = ['999','888','777','666','555'];
            state.title = '测试标题';
            save();
        }""")
        pg.reload()
        pg.wait_for_timeout(900)
        kept = pg.evaluate("""() => ({
            name: state.rows[0].name,
            scores: state.rows[0].scores,
            title: state.title
        })""")
        ck("刷新后节目名保留", kept['name'] == '持久化测试', kept['name'])
        ck("刷新后分数保留", kept['scores'] == ['999','888','777','666','555'], str(kept['scores']))
        ck("刷新后标题保留", kept['title'] == '测试标题', kept['title'])

        # ============ 9. 恢复默认设置 ============
        section("【9】恢复默认设置（分数要保留）")
        # 先把第1行名字恢复成预置名（前面持久化测试改过名）
        pg.evaluate("""() => {
            state.rows[0].name = '《示例节目一》';
            state.rows[0].actor = '示例演出团队一';
            state.maxScore = 100;
            state.decimals = 3;
            state.judgeCount = 7;
            state.awards = {first:1,second:2,third:3};
            state.rows[0].scores = ['9800','9700','9600','9500','9400','9300','9200'];
            save(); renderBody();
        }""")
        pg.wait_for_timeout(250)
        pg.once("dialog", lambda d: d.accept())
        pg.click('button:has-text("恢复默认设置")')
        pg.wait_for_timeout(700)
        reset = pg.evaluate("""() => ({
            max: state.maxScore, dec: state.decimals, judges: state.judgeCount,
            awards: state.awards, score0: state.rows[0].scores
        })""")
        ck("满分恢复 10", reset['max'] == 10, str(reset['max']))
        ck("小数位恢复 2", reset['dec'] == 2, str(reset['dec']))
        ck("评委恢复 5", reset['judges'] == 5, str(reset['judges']))
        ck("奖项恢复 0", reset['awards'] == {'first':0,'second':0,'third':0}, str(reset['awards']))
        ck("★分数没被清除", len(reset['score0']) >= 5 and reset['score0'][0] == '9800', str(reset['score0'][:3]))

        # ============ 10. 抽签切换 ============
        section("【10】现场抽签顺序切换")
        pg.evaluate("""() => {
            state.drawOrder = false;
            document.getElementById('chkDrawOrder').checked = false;
            state.rows.forEach((r,i) => { r.no = i+1; });
            save(); renderBody();
        }""")
        pg.wait_for_timeout(200)
        # 勾选 → 清空序号
        dlg_msgs = []
        def on_d(d):
            dlg_msgs.append(d.message)
            d.accept()
        pg.once("dialog", on_d)
        pg.check("#chkDrawOrder")
        pg.wait_for_timeout(600)
        ck("勾选弹确认框", len(dlg_msgs) > 0)
        nos = pg.evaluate("() => state.rows.slice(0,5).map(r => String(r.no === undefined || r.no === null ? '' : r.no).trim())")
        ck("序号已清空", all(x == '' for x in nos), str(nos))
        ck("抽签状态开启", pg.evaluate("() => state.drawOrder"))
        ck("节目名未被清", pg.evaluate("() => (state.rows[0].name||'')") != '')

        # 取消 → 重新编号
        pg.once("dialog", lambda d: d.accept())
        pg.evaluate("() => document.getElementById('chkDrawOrder').click()")
        pg.wait_for_timeout(600)
        nos2 = pg.evaluate("() => state.rows.slice(0,5).map(r => r.no)")
        ck("取消后重新编号", nos2 == [1,2,3,4,5], str(nos2))

        # ============ 11. 右键菜单 ============
        section("【11】右键菜单")
        ck("行右键 3 项", pg.evaluate("() => document.querySelectorAll('#ctxMenu .item').length") == 3)
        items = pg.evaluate("() => [...document.querySelectorAll('#ctxMenu .item')].map(e=>e.textContent.trim())")
        ck("含上方插入", any('上方插入' in x for x in items), str(items))
        ck("含下方插入", any('下方插入' in x for x in items))
        ck("含删除", any('删除' in x for x in items))
        ck("单元格菜单存在", pg.evaluate("() => !!document.getElementById('cellMenu')"))

        # ============ 12. 界面细节 ============
        section("【12】界面细节")
        ck("序号列固定", pg.evaluate("() => document.querySelector('#theadRow th').classList.contains('fixed-col')"))
        ck("序号列无下拉箭头", pg.evaluate("() => !document.querySelector('#theadRow th:first-child .caret')"))
        ph = pg.evaluate("() => [...new Set([...document.querySelectorAll('td.score input')].map(i=>i.placeholder))]")
        ck("分数框无占位符", ph == [''], str(ph))
        ck("有导出列勾选区", pg.is_visible("#exportCols"))
        ck("有比赛设置按钮", pg.locator('button:has-text("导出比赛设置")').count() == 1)

        # ============ 13. 无报错 ============
        section("【13】JS 报错")
        if errs:
            for e in errs[:5]:
                print(f"    ⚠️ {e}")
        ck("无 JS 报错", len(errs) == 0, " | ".join(errs[:2]))

        browser.close()

    # ============ 汇总 ============
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in R if ok)
    total = len(R)
    print(f"测试结果: {passed}/{total} 通过")
    print("=" * 60)
    if passed < total:
        print("\n未通过项：")
        for name, ok, detail in R:
            if not ok:
                print(f"  ✗ {name}  {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())


