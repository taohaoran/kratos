#!/usr/bin/env python3
"""build-docs-html.py — 部署时把目录下 Markdown 默认渲染为 HTML 文档页，并强制生成导览 index.md。

解决痛点：GitHub Pages 纯静态托管 .md 时浏览器直接显示源码、阅读体验差；站点缺少能覆盖全部文档的导览页。
本脚本在部署前统一完成两件事（默认开启）：
  1) md 默认转 html：递归渲染部署目录下所有 .md → 同目录同名 .html（.md 保留为源），
     文档间相对链接 .md → .html 自动改写；指向 .html 的图片引用改写为「打开交互式图」按钮。
  2) 导览文件（强制）：在部署目录根生成 index.md，按「系统级 → 域级 → 页级」三级中文层级组织，
     并渲染为 index.html 作为站点根入口，保证任何文档都可从导览到达，无孤儿页面。

用法:
  python3 build-docs-html.py <site_dir> [--site-name "站点名"] [--group-label "core=核心|ai=智能"]
      [--label-map "adapters=适配器|backtest=回测|data=数据"]
依赖: pip install markdown

行为:
  - 生成导览 index.md（系统级/域级/页级三级中文层级）并渲染为 index.html
  - 递归渲染 site_dir 下所有 .md → 同目录同名 .html
  - 每页顶部生成「← 站点首页」面包屑与所属板块标签（按一级子目录分组）
"""
import argparse
import re
import sys
from pathlib import Path

import markdown

DOC_CSS = """
  :root {
    --bg: #f5f7fa; --card: #ffffff; --ink: #1c2733; --ink-2: #5a6b7c;
    --line: #e3e8ee; --accent: #1f5f8b; --accent-soft: #e8f1f8;
    --code-bg: #f0f3f6; --quote: #eef4f9; --code-ink: #0f1a24;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI", sans-serif;
    background: var(--bg); color: var(--ink); line-height: 1.75;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 880px; margin: 0 auto; padding: 32px 24px 64px; }
  nav.topnav {
    display: flex; align-items: center; gap: 10px; margin-bottom: 20px;
    font-size: 13px; color: var(--ink-2);
  }
  nav.topnav a { color: var(--accent); text-decoration: none; font-weight: 600; }
  nav.topnav a:hover { text-decoration: underline; }
  nav.topnav .crumb {
    background: var(--card); border: 1px solid var(--line); border-radius: 999px;
    padding: 3px 12px; font-size: 12px; font-weight: 600; color: var(--ink-2);
  }
  article.doc {
    background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 36px 44px;
  }
  article.doc h1 { font-size: 27px; line-height: 1.4; letter-spacing: -0.01em; padding-bottom: 14px; border-bottom: 1px solid var(--line); margin-bottom: 26px; }
  article.doc h2 { font-size: 20px; margin: 36px 0 14px; padding-bottom: 8px; border-bottom: 1px solid #eef1f5; }
  article.doc h3 { font-size: 16.5px; margin: 26px 0 10px; }
  article.doc h4 { font-size: 15px; margin: 20px 0 8px; }
  article.doc p { margin: 12px 0; }
  article.doc ul, article.doc ol { margin: 12px 0; padding-left: 26px; }
  article.doc li { margin: 5px 0; }
  article.doc a { color: var(--accent); text-decoration: none; }
  article.doc a:hover { text-decoration: underline; }
  article.doc table { border-collapse: collapse; width: 100%; margin: 18px 0; font-size: 14px; display: block; overflow-x: auto; }
  article.doc th { background: #f0f4f8; text-align: left; padding: 9px 13px; border: 1px solid var(--line); font-weight: 600; white-space: nowrap; }
  article.doc td { padding: 9px 13px; border: 1px solid var(--line); vertical-align: top; }
  article.doc tr:nth-child(even) td { background: #fafbfc; }
  article.doc code { background: var(--code-bg); padding: 2px 6px; border-radius: 4px; font-size: 13px; font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; }
  article.doc pre { background: var(--code-ink); color: #e6edf3; padding: 16px 18px; border-radius: 8px; overflow-x: auto; margin: 16px 0; line-height: 1.6; }
  article.doc pre code { background: none; color: inherit; padding: 0; }
  article.doc blockquote { border-left: 4px solid #b9cddd; background: var(--quote); margin: 16px 0; padding: 10px 16px; color: var(--ink-2); border-radius: 0 8px 8px 0; }
  article.doc blockquote p { margin: 4px 0; }
  article.doc img { max-width: 100%; border-radius: 8px; border: 1px solid var(--line); }
  article.doc hr { border: none; border-top: 1px solid var(--line); margin: 28px 0; }
  a.diagram-link {
    display: inline-block; margin: 4px 0;
    background: var(--accent-soft); border: 1px solid #cfe0ee; color: var(--accent);
    border-radius: 8px; padding: 7px 16px; font-size: 13.5px; font-weight: 600;
    text-decoration: none !important; transition: background 0.15s, border-color 0.15s;
  }
  a.diagram-link:hover { background: #dbeaf5; border-color: var(--accent); }
  a.diagram-link::before { content: "打开交互式图："; font-weight: 400; }
  footer.doc-foot { margin-top: 24px; font-size: 12.5px; color: var(--ink-2); text-align: center; }

  /* ---- 导览页专属样式 ---- */
  .nav-section { margin-bottom: 32px; }
  .nav-section > h2 {
    font-size: 18px; margin: 0 0 14px; padding: 10px 16px;
    background: var(--accent-soft); border-radius: 8px;
    border-left: 4px solid var(--accent); color: var(--ink);
  }
  .nav-domain {
    background: var(--card); border: 1px solid var(--line); border-radius: 10px;
    padding: 18px 22px; margin-bottom: 14px;
  }
  .nav-domain > h3 {
    font-size: 15.5px; margin: 0 0 10px; color: var(--accent);
    display: flex; align-items: center; gap: 8px;
  }
  .nav-domain > h3 .en {
    font-size: 12px; font-weight: 400; color: var(--ink-2);
    background: var(--bg); padding: 2px 8px; border-radius: 4px;
  }
  .nav-domain > ul { list-style: none; padding: 0; margin: 0; }
  .nav-component {
    margin: 8px 0; padding-left: 12px; border-left: 2px solid var(--line);
  }
  .nav-component > .comp-label {
    font-size: 13.5px; font-weight: 600; color: var(--ink-2); margin: 6px 0 4px;
  }
  .nav-component > ul { list-style: none; padding: 0; margin: 0; }
  .nav-component > ul li, .nav-domain > ul li {
    padding: 3px 0; font-size: 14px;
  }
  .nav-component > ul li a, .nav-domain > ul li a {
    color: var(--ink); text-decoration: none;
  }
  .nav-component > ul li a:hover, .nav-domain > ul li a:hover {
    color: var(--accent); text-decoration: underline;
  }
  .nav-component > ul li a .tag {
    display: inline-block; font-size: 11.5px; color: var(--accent);
    background: var(--accent-soft); padding: 1px 7px; border-radius: 4px;
    margin-left: 6px; font-weight: 400;
  }
  .nav-stats { font-size: 13px; color: var(--ink-2); margin-top: 20px; }

  @media (max-width: 640px) {
    .wrap { padding: 20px 12px 40px; }
    article.doc { padding: 24px 18px; }
    article.doc h1 { font-size: 22px; }
  }
"""

# ---- 内置中文标签映射（可通过 --label-map 扩展/覆盖） ----

# 系统级页面文件名 → 中文标签
SYSTEM_PAGE_LABELS = {
    "readme": "项目说明",
    "system-overview": "系统概览",
    "system-architecture": "系统架构图",
    "system-dataflow": "系统数据流",
    "system-trade-sequence": "交易时序",
}

# 域级目录名 → 中文标签
DOMAIN_LABELS = {
    "adapters": "适配器",
    "analysis-indicators": "分析与指标",
    "backtest": "回测",
    "core-foundations": "核心基础",
    "data": "数据",
    "domain-model": "领域模型",
    "execution": "执行",
    "live-trading": "实盘交易",
    "portfolio-risk": "投资组合与风险",
    "python-binding": "Python 绑定",
    "serialization": "序列化",
    "tooling": "工具",
}

# 组件级目录名 → 中文标签
COMPONENT_LABELS = {
    "adapters-crypto": "加密货币适配器",
    "adapters-traditional": "传统交易所适配器",
    "analysis-statistics": "分析统计",
    "indicators-library": "指标库",
    "backtest-data": "回测数据",
    "backtest-engine": "回测引擎",
    "backtest-venv": "回测环境",
    "common-actor-lifecycle": "Actor 生命周期",
    "common-cache": "缓存",
    "common-logging-config": "日志配置",
    "common-message-bus": "消息总线",
    "core-datetime-collections": "日期时间与集合",
    "data-client-feeds": "数据客户端与订阅",
    "data-engine": "数据引擎",
    "data-option-chains": "期权链数据",
    "model-events-accounts": "事件与账户",
    "model-identifiers-types": "标识符与类型",
    "model-instruments-reports": "工具与报告",
    "model-orders-orderbook": "订单与订单簿",
    "execution-cache-messages": "执行缓存消息",
    "execution-engine": "执行引擎",
    "execution-matching": "撮合",
    "infrastructure-services": "基础设施服务",
    "live-engine": "实盘引擎",
    "live-persistence": "持久化",
    "network-transport": "网络传输",
    "system-orchestration": "系统编排",
    "portfolio-engine": "投资组合引擎",
    "risk-engine": "风险引擎",
    "pyo3-binding-layer": "PyO3 绑定层",
    "python-control-plane": "Python 控制面",
    "serialization-capnp-arrow": "Cap'n Proto / Arrow 序列化",
    "serialization-sbe": "SBE 序列化",
    "cli-plugin": "CLI 插件",
    "testkit": "测试工具包",
}

# 页面后缀 → 中文视图类型标签
PAGE_SUFFIX_LABELS = {
    "-architecture": "架构视图",
    "-dataflow": "数据流视图",
    "-sequence": "时序视图",
    "-lifecycle": "生命周期视图",
}


def parse_group_labels(spec: str) -> dict:
    """--group-label 'core=核心|ai=AI' → {'core':'核心','ai':'AI'}"""
    labels = {}
    if not spec:
        return labels
    for pair in spec.split("|"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            labels[k.strip()] = v.strip()
    return labels


def parse_label_map(spec: str) -> dict:
    """--label-map 'adapters=适配器|backtest=回测' → {'adapters':'适配器','backtest':'回测'}"""
    return parse_group_labels(spec)


def extract_title(md_text: str) -> str:
    m = re.search(r"^#\s+(.+?)\s*$", md_text, re.MULTILINE)
    return m.group(1).strip() if m else "文档"


def preprocess(md_text: str) -> str:
    """把指向 .html 的图片引用改为交互图链接按钮。"""
    def repl(m):
        alt, url = m.group(1), m.group(2)
        return f'<a class="diagram-link" href="{url}" target="_blank" rel="noopener">{alt}</a>'
    return re.sub(r"!\[([^\]]*)\]\(([^)]+\.html)([^)]*)\)", repl, md_text)


def rewrite_links(html: str) -> str:
    """把渲染后指向 .md 的相对链接改写为 .html。"""
    def repl(m):
        anchor = m.group(2) or ""
        return f'href="{m.group(1)}.html{anchor}"'
    return re.sub(r'href="([^"]+)\.md(#.*)?"', repl, html)


def render_one(md_path: Path, root: Path, site_name: str, group_labels: dict) -> Path:
    md_text = md_path.read_text(encoding="utf-8")
    title = extract_title(md_text)
    body = markdown.markdown(
        preprocess(md_text),
        extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list"],
        output_format="html5",
    )
    body = rewrite_links(body)

    rel = md_path.relative_to(root)
    group = rel.parts[0] if len(rel.parts) > 1 else ""
    # 按文件相对站点根的真实深度计算返回首页的相对路径（修复深层页面 ../index.html 404）
    depth = len(rel.parts) - 1
    back = "index.html" if depth == 0 else ("../" * depth) + "index.html"
    group_label = group_labels.get(group, group) if group else ""

    crumb = f'<span class="crumb">{group_label}</span>' if group_label else ""
    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} · {site_name}</title>
<style>{DOC_CSS}</style>
</head>
<body>
<div class="wrap">
  <nav class="topnav">
    <a href="{back}">← {site_name}</a>
    {crumb}
  </nav>
  <article class="doc">
{body}
  </article>
  <footer class="doc-foot">{site_name} · 渲染文档</footer>
</div>
</body>
</html>
"""
    out = md_path.with_suffix(".html")
    out.write_text(page, encoding="utf-8")
    return out


def collect_docs(root: Path):
    """返回 (全部 .md 列表, 独立 .html 列表)。
    排除导览自身 index.md/index.html；.md 渲染出的同名 .html 不算独立 html。"""
    mds = sorted(p for p in root.rglob("*.md") if p.name != "index.md")
    rendered = {p.with_suffix(".html") for p in mds}
    htmls = sorted(
        p for p in root.rglob("*.html")
        if p.name != "index.html" and p not in rendered
    )
    return mds, htmls


def kebab_to_label(name: str) -> str:
    """把 kebab-case 转为可读标签（兜底用，未在映射表中时）。"""
    return name.replace("-", " ").strip().title()


def get_label(name: str, builtin: dict, extra: dict) -> str:
    """从内置映射和扩展映射中查找中文标签。"""
    key = name.lower()
    if key in builtin:
        return builtin[key]
    if key in extra:
        return extra[key]
    if name in builtin:
        return builtin[name]
    if name in extra:
        return extra[name]
    return kebab_to_label(name)


def get_content_root(root: Path) -> Path:
    """检测内容根目录：如果站点根下只有一个子目录，且所有文档都在其中，则返回该子目录。
    否则返回站点根本身。"""
    subdirs = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if len(subdirs) == 1:
        # 检查所有 md/html 是否都在这个子目录里
        sub = subdirs[0]
        others = [p for p in root.rglob("*.md") if p.parent == root]
        others += [p for p in root.rglob("*.html") if p.parent == root and p.name != "index.html"]
        if not others:
            return sub
    return root


def get_page_display(rel_path: Path, parent_dir: str, is_system: bool, extra_labels: dict) -> tuple:
    """获取页面的显示标签和视图类型标签。
    is_system=True 表示这是系统级页面（直接在内容根下）。
    parent_dir 是该文件所在的直接父目录名（用于组件级页面）。
    返回 (显示名, 视图类型tag或None)。"""
    stem = rel_path.stem

    # 系统级页面：先查 SYSTEM_PAGE_LABELS，再尝试后缀匹配
    if is_system:
        if stem.lower() in SYSTEM_PAGE_LABELS:
            return SYSTEM_PAGE_LABELS[stem.lower()], None
        for suffix, tag in sorted(PAGE_SUFFIX_LABELS.items(), key=lambda x: -len(x[0])):
            if stem.endswith(suffix):
                base = stem[:-len(suffix)]
                return get_label(base, SYSTEM_PAGE_LABELS, extra_labels), tag
        return get_label(stem, SYSTEM_PAGE_LABELS, extra_labels), None

    # 组件级页面：
    # 1) 如果是 .md 且 stem 与父目录同名 → 这是概述页，用父目录标签（域级或组件级）
    if rel_path.suffix == ".md" and stem == parent_dir:
        return get_label(parent_dir, {**DOMAIN_LABELS, **COMPONENT_LABELS}, extra_labels), None

    # 2) 尝试后缀匹配（组件详情页，如 adapters-crypto-architecture.html）
    for suffix, tag in sorted(PAGE_SUFFIX_LABELS.items(), key=lambda x: -len(x[0])):
        if stem.endswith(suffix):
            base = stem[:-len(suffix)]
            return get_label(base, COMPONENT_LABELS, extra_labels), tag

    # 3) 无后缀，直接查标签
    return get_label(stem, {**COMPONENT_LABELS, **DOMAIN_LABELS}, extra_labels), None


def generate_nav(root: Path, site_name: str, extra_labels: dict) -> Path:
    """生成导览 index.md：按「系统级 → 域级 → 页级」三级中文层级组织。"""
    mds, htmls = collect_docs(root)
    content_root = get_content_root(root)
    rel_content = content_root.relative_to(root)

    # 合并所有文件
    all_files = list(mds) + list(htmls)

    # 按相对 content_root 的路径分类
    system_files = []   # 直接在 content_root 下的文件
    domains: dict = {}  # domain_name -> list of files (relative to content_root)

    for p in all_files:
        try:
            rel = p.relative_to(content_root)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) == 1:
            # 直接在 content_root 下 → 系统级
            system_files.append((p, rel))
        else:
            # 在某域名目录下 → 域级
            domain = parts[0]
            domains.setdefault(domain, []).append((p, rel))

    # ---- 生成 Markdown ----
    lines = [f"# {site_name}", ""]
    lines.append("> 本站导览：按「系统级 → 域级 → 页级」三级结构组织，所有文档均已渲染为 HTML。")
    lines.append("")

    # 统计
    total_pages = len(all_files)

    # ---- 系统级 ----
    if system_files:
        lines.append("## 系统级")
        lines.append("")
        # 排序：先 README，再 system-*
        def system_sort_key(item):
            rel = item[1]
            name = rel.stem.lower()
            if name == "readme":
                return (0, str(rel))
            return (1, str(rel))
        for p, rel in sorted(system_files, key=system_sort_key):
            display, _ = get_page_display(rel, "", True, extra_labels)
            href = rel.as_posix()
            if p.suffix == ".md":
                href = rel.with_suffix(".html").as_posix()
            # 修正 href：加上 content_root 的相对路径前缀
            if len(rel_content.parts) > 0 and rel_content != Path("."):
                href = str(rel_content / href)
            lines.append(f"- [{display}]({href})")
        lines.append("")

    # ---- 域级 ----
    for domain in sorted(domains.keys()):
        files = domains[domain]
        domain_cn = get_label(domain, DOMAIN_LABELS, extra_labels)
        lines.append(f"## {domain_cn}")
        lines.append("")

        # 分类：域名自身的总览页 vs 组件下的页
        domain_overview = []  # domain.md 等直接在域名目录下的文件
        components: dict = {}  # component_name -> list of (file, rel)

        for p, rel in sorted(files, key=lambda x: x[1].as_posix()):
            parts = rel.parts
            if len(parts) == 2:
                # 直接在域名目录下 → 域级总览
                domain_overview.append((p, rel))
            else:
                # 在组件子目录下
                comp = parts[1]
                components.setdefault(comp, []).append((p, rel))

        # 域级总览
        for p, rel in domain_overview:
            display, _ = get_page_display(rel, domain, False, extra_labels)
            href = rel.as_posix()
            if p.suffix == ".md":
                href = rel.with_suffix(".html").as_posix()
            if len(rel_content.parts) > 0 and rel_content != Path("."):
                href = str(rel_content / href)
            lines.append(f"- [{display}]({href})")

        # 组件级
        for comp in sorted(components.keys()):
            comp_cn = get_label(comp, COMPONENT_LABELS, extra_labels)
            lines.append(f"### {comp_cn}")
            for p, rel in sorted(components[comp], key=lambda x: x[1].as_posix()):
                display, tag = get_page_display(rel, comp, False, extra_labels)
                href = rel.as_posix()
                if p.suffix == ".md":
                    href = rel.with_suffix(".html").as_posix()
                if len(rel_content.parts) > 0 and rel_content != Path("."):
                    href = str(rel_content / href)
                if tag:
                    lines.append(f"- [{display} · {tag}]({href})")
                else:
                    lines.append(f"- [{display}]({href})")
        lines.append("")

    lines.append(f"共 {total_pages} 个页面。")
    nav_md = root / "index.md"
    nav_md.write_text("\n".join(lines), encoding="utf-8")

    # ---- 渲染为带样式的 HTML ----
    nav_html_body = markdown.markdown(
        "\n".join(lines),
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html5",
    )
    nav_html_body = rewrite_links(nav_html_body)

    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{site_name}</title>
<style>{DOC_CSS}</style>
</head>
<body>
<div class="wrap">
  <article class="doc">
{nav_html_body}
  </article>
  <footer class="doc-foot">{site_name} · 导览</footer>
</div>
</body>
</html>
"""
    nav_html = root / "index.html"
    nav_html.write_text(page, encoding="utf-8")
    return nav_md


def main():
    ap = argparse.ArgumentParser(description="Markdown 渲染为 HTML 并生成导览 index（GitHub Pages 部署时默认执行）")
    ap.add_argument("docs_dir", type=Path, help="站点目录（默认当前目录）", nargs="?", default=Path("."))
    ap.add_argument("--site-name", default="架构文档", help="站点名（用于导览标题/面包屑/页脚/页面标题）")
    ap.add_argument("--group-label", default="", help='一级子目录分组标签，如 "core=核心|ai=智能"')
    ap.add_argument("--label-map", default="", help='自定义中文标签映射，如 "adapters=适配器|backtest=回测"')
    args = ap.parse_args()

    root = args.docs_dir.resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory", file=sys.stderr)
        return 2
    group_labels = parse_group_labels(args.group_label)
    extra_labels = parse_label_map(args.label_map)

    nav = generate_nav(root, args.site_name, extra_labels)
    print(f"nav: {nav.relative_to(root)}")

    mds = sorted(root.rglob("*.md"))  # 含导览 index.md
    for md in mds:
        out = render_one(md, root, args.site_name, group_labels)
        print(f"built: {out.relative_to(root)}")
    print(f"done: {len(mds)} markdown files rendered (incl. nav index)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
