import re
import os
import json
import markdown

sop_dir = os.path.dirname(os.path.abspath(__file__))

docs_config = [
    {
        "id": "tong-quan",
        "file": "README.md",
        "title": "Tổng Quan Hệ Thống",
        "category": "Cẩm Nang Chung",
        "badge": "Chung"
    },
    {
        "id": "cham-cong",
        "file": "cham_cong.md",
        "title": "Quy Định Chấm Công & Đi Trễ",
        "category": "Nghiệp Vụ Nhân Sự",
        "badge": "Nhân sự"
    },
    {
        "id": "duyet-ot",
        "file": "duyet_ot.md",
        "title": "Quy Trình Duyệt Giờ & Tăng Ca (OT)",
        "category": "Nghiệp Vụ Nhân Sự",
        "badge": "Lương & OT"
    },
    {
        "id": "dong-ca",
        "file": "dong_ca.md",
        "title": "Quy Trình Đóng Ca & Chốt Két",
        "category": "Vận Hành Quầy & Thu Ngân",
        "badge": "Quầy bar"
    },
    {
        "id": "su-co",
        "file": "su_co.md",
        "title": "Xử Lý Sự Cố Kỹ Thuật & POS",
        "category": "Vận Hành Quầy & Thu Ngân",
        "badge": "Kỹ thuật"
    }
]

rendered_docs = []
for doc in docs_config:
    file_path = os.path.join(sop_dir, doc["file"])
    with open(file_path, "r", encoding="utf-8") as f:
        raw_text = f.read()
    
    html_content = markdown.markdown(raw_text, extensions=["extra", "tables", "fenced_code", "nl2br"])
    html_content = re.sub(r'href="\/cham_cong"', 'href="#cham-cong" onclick="switchDoc(\'cham-cong\'); return false;"', html_content)
    html_content = re.sub(r'href="\/duyet_ot"', 'href="#duyet-ot" onclick="switchDoc(\'duyet-ot\'); return false;"', html_content)
    html_content = re.sub(r'href="\/dong_ca"', 'href="#dong-ca" onclick="switchDoc(\'dong-ca\'); return false;"', html_content)
    html_content = re.sub(r'href="\/su_co"', 'href="#su-co" onclick="switchDoc(\'su-co\'); return false;"', html_content)
    html_content = re.sub(r'href="\/"', 'href="#tong-quan" onclick="switchDoc(\'tong-quan\'); return false;"', html_content)
    rendered_docs.append({
        "id": doc["id"],
        "title": doc["title"],
        "category": doc["category"],
        "badge": doc["badge"],
        "html": html_content
    })

# Group categories
categories = {}
for doc in rendered_docs:
    cat = doc["category"]
    if cat not in categories:
        categories[cat] = []
    categories[cat].append(doc)

sidebar_nav_html = ""
for cat, docs in categories.items():
    sidebar_nav_html += f'<div class="nav-category"><div class="category-title">{cat}</div><div class="category-links">'
    for d in docs:
        sidebar_nav_html += f'''
        <button class="nav-item" data-id="{d['id']}" onclick="switchDoc('{d['id']}')">
            <span class="nav-item-title">{d['title']}</span>
            <span class="nav-badge">{d['badge']}</span>
        </button>
        '''
    sidebar_nav_html += '</div></div>'

content_sections_html = ""
for idx, d in enumerate(rendered_docs):
    active_class = "active" if idx == 0 else ""
    content_sections_html += f'''
    <section id="doc-{d['id']}" class="doc-section {active_class}">
        <div class="doc-meta-bar">
            <span class="doc-category-tag">{d['category']}</span>
            <span class="doc-divider">/</span>
            <span class="doc-active-title">{d['title']}</span>
        </div>
        <article class="markdown-body">
            {d['html']}
        </article>
    </section>
    '''

template = f'''<!DOCTYPE html>
<html lang="vi" data-theme="dark">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
    <title>FnBOps - Cẩm Nang Vận Hành & SOP</title>
    <style>
        :root {{
            --bg-base: #0a0c10;
            --bg-surface: #12151e;
            --bg-surface-hover: #181d2a;
            --bg-card: #151924;
            --border-subtle: rgba(255, 255, 255, 0.08);
            --border-strong: rgba(255, 255, 255, 0.16);
            --text-primary: #f1f5f9;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --accent-primary: #0d9488;
            --accent-hover: #14b8a6;
            --accent-glow: rgba(13, 148, 136, 0.15);
            --code-bg: #1a1f2c;
            --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
            --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }}

        [data-theme="light"] {{
            --bg-base: #f8fafc;
            --bg-surface: #ffffff;
            --bg-surface-hover: #f1f5f9;
            --bg-card: #ffffff;
            --border-subtle: rgba(0, 0, 0, 0.08);
            --border-strong: rgba(0, 0, 0, 0.16);
            --text-primary: #0f172a;
            --text-secondary: #475569;
            --text-muted: #94a3b8;
            --accent-primary: #0f766e;
            --accent-hover: #0d9488;
            --accent-glow: rgba(15, 118, 110, 0.1);
            --code-bg: #f1f5f9;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: var(--font-sans);
            background-color: var(--bg-base);
            color: var(--text-primary);
            line-height: 1.6;
            display: flex;
            min-height: 100vh;
            -webkit-font-smoothing: antialiased;
        }}

        /* SIDEBAR */
        #sidebar {{
            width: 320px;
            background: var(--bg-surface);
            border-right: 1px solid var(--border-subtle);
            display: flex;
            flex-direction: column;
            position: fixed;
            top: 0;
            bottom: 0;
            left: 0;
            z-index: 50;
            transition: transform 0.25s ease;
        }}

        .sidebar-header {{
            padding: 24px 20px 16px;
            border-bottom: 1px solid var(--border-subtle);
        }}

        .brand-title {{
            font-size: 1.1rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            color: var(--text-primary);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}

        .brand-badge {{
            font-size: 0.7rem;
            padding: 2px 8px;
            background: var(--accent-glow);
            color: var(--accent-primary);
            border: 1px solid var(--accent-primary);
            border-radius: 9999px;
            font-weight: 600;
        }}

        .search-box {{
            margin-top: 14px;
            position: relative;
        }}

        .search-input {{
            width: 100%;
            padding: 8px 12px;
            background: var(--bg-base);
            border: 1px solid var(--border-subtle);
            border-radius: 6px;
            color: var(--text-primary);
            font-size: 0.85rem;
            outline: none;
            transition: border-color 0.15s;
        }}

        .search-input:focus {{
            border-color: var(--accent-primary);
        }}

        .sidebar-nav {{
            flex: 1;
            overflow-y: auto;
            padding: 16px 12px;
        }}

        .nav-category {{
            margin-bottom: 20px;
        }}

        .category-title {{
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--text-muted);
            padding: 4px 10px 8px;
        }}

        .category-links {{
            display: flex;
            flex-direction: column;
            gap: 2px;
        }}

        .nav-item {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            width: 100%;
            padding: 9px 12px;
            background: transparent;
            border: none;
            border-radius: 6px;
            color: var(--text-secondary);
            font-size: 0.875rem;
            text-align: left;
            cursor: pointer;
            transition: all 0.15s ease;
        }}

        .nav-item:hover {{
            background: var(--bg-surface-hover);
            color: var(--text-primary);
        }}

        .nav-item.active {{
            background: var(--accent-glow);
            color: var(--accent-primary);
            font-weight: 600;
        }}

        .nav-badge {{
            font-size: 0.7rem;
            padding: 1px 6px;
            border-radius: 4px;
            background: rgba(255, 255, 255, 0.06);
            color: var(--text-muted);
        }}

        .nav-item.active .nav-badge {{
            background: var(--accent-primary);
            color: #ffffff;
        }}

        .sidebar-footer {{
            padding: 14px 20px;
            border-top: 1px solid var(--border-subtle);
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 0.8rem;
        }}

        .ext-link {{
            color: var(--text-secondary);
            text-decoration: none;
            transition: color 0.15s;
        }}

        .ext-link:hover {{
            color: var(--accent-primary);
        }}

        .theme-toggle-btn {{
            background: transparent;
            border: 1px solid var(--border-subtle);
            padding: 4px 10px;
            border-radius: 4px;
            color: var(--text-secondary);
            cursor: pointer;
            font-size: 0.75rem;
        }}

        /* MAIN CONTENT */
        #main {{
            margin-left: 320px;
            flex: 1;
            min-width: 0;
            padding: 40px 60px 80px;
            display: flex;
            justify-content: center;
        }}

        .main-inner {{
            width: 100%;
            max-width: 860px;
        }}

        .mobile-header {{
            display: none;
            position: sticky;
            top: 0;
            background: var(--bg-surface);
            border-bottom: 1px solid var(--border-subtle);
            padding: 14px 20px;
            z-index: 40;
            align-items: center;
            justify-content: space-between;
        }}

        .doc-section {{
            display: none;
        }}

        .doc-section.active {{
            display: block;
            animation: fadeIn 0.15s ease-out;
        }}

        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(4px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .doc-meta-bar {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.82rem;
            color: var(--text-muted);
            margin-bottom: 24px;
            padding-bottom: 14px;
            border-bottom: 1px solid var(--border-subtle);
        }}

        .doc-category-tag {{
            font-weight: 600;
            color: var(--accent-primary);
        }}

        .doc-active-title {{
            color: var(--text-primary);
            font-weight: 500;
        }}

        /* MARKDOWN BODY STYLES */
        .markdown-body h1 {{
            font-size: 2rem;
            font-weight: 700;
            letter-spacing: -0.03em;
            margin-bottom: 20px;
            color: var(--text-primary);
            line-height: 1.25;
        }}

        .markdown-body h2 {{
            font-size: 1.35rem;
            font-weight: 600;
            letter-spacing: -0.02em;
            margin-top: 36px;
            margin-bottom: 14px;
            color: var(--text-primary);
            border-bottom: 1px solid var(--border-subtle);
            padding-bottom: 8px;
        }}

        .markdown-body h3 {{
            font-size: 1.1rem;
            font-weight: 600;
            margin-top: 24px;
            margin-bottom: 10px;
            color: var(--text-primary);
        }}

        .markdown-body p {{
            margin-bottom: 16px;
            color: var(--text-secondary);
            font-size: 0.96rem;
            line-height: 1.7;
        }}

        .markdown-body ul, .markdown-body ol {{
            margin-bottom: 18px;
            padding-left: 24px;
            color: var(--text-secondary);
        }}

        .markdown-body li {{
            margin-bottom: 8px;
            font-size: 0.95rem;
            line-height: 1.6;
        }}

        .markdown-body strong {{
            color: var(--text-primary);
            font-weight: 600;
        }}

        .markdown-body a {{
            color: var(--accent-primary);
            text-decoration: none;
            border-bottom: 1px dotted var(--accent-primary);
        }}

        .markdown-body a:hover {{
            color: var(--accent-hover);
        }}

        .markdown-body code {{
            background: var(--code-bg);
            padding: 2px 6px;
            border-radius: 4px;
            font-family: var(--font-mono);
            font-size: 0.88rem;
            color: var(--accent-hover);
            border: 1px solid var(--border-subtle);
        }}

        .markdown-body pre {{
            background: var(--code-bg);
            padding: 16px;
            border-radius: 8px;
            overflow-x: auto;
            margin-bottom: 20px;
            border: 1px solid var(--border-subtle);
        }}

        .markdown-body pre code {{
            background: transparent;
            padding: 0;
            border: none;
            color: var(--text-primary);
            font-size: 0.88rem;
        }}

        .markdown-body blockquote {{
            margin: 20px 0;
            padding: 14px 18px;
            border-left: 4px solid var(--accent-primary);
            background: var(--bg-surface);
            border-radius: 0 6px 6px 0;
            color: var(--text-secondary);
            font-size: 0.92rem;
        }}

        .markdown-body table {{
            width: 100%;
            border-collapse: collapse;
            margin: 24px 0;
            font-size: 0.92rem;
        }}

        .markdown-body th, .markdown-body td {{
            padding: 10px 14px;
            border: 1px solid var(--border-subtle);
            text-align: left;
        }}

        .markdown-body th {{
            background: var(--bg-surface);
            font-weight: 600;
            color: var(--text-primary);
        }}

        .markdown-body tr:nth-child(even) {{
            background: rgba(255, 255, 255, 0.02);
        }}

        /* RESPONSIVE */
        @media (max-width: 900px) {{
            #sidebar {{
                transform: translateX(-100%);
            }}
            #sidebar.open {{
                transform: translateX(0);
            }}
            #main {{
                margin-left: 0;
                padding: 24px 20px 60px;
            }}
            .mobile-header {{
                display: flex;
            }}
            .backdrop {{
                display: none;
                position: fixed;
                inset: 0;
                background: rgba(0, 0, 0, 0.6);
                z-index: 45;
            }}
            .backdrop.open {{
                display: block;
            }}
        }}
    </style>
</head>
<body>
    <div id="backdrop" class="backdrop" onclick="toggleSidebar()"></div>

    <aside id="sidebar">
        <div class="sidebar-header">
            <div class="brand-title">
                <span>FnBOps Store</span>
                <span class="brand-badge">SOP v2.4</span>
            </div>
            <div class="search-box">
                <input type="text" id="searchInput" class="search-input" placeholder="Tìm kiếm tài liệu SOP..." oninput="handleSearch(this.value)">
            </div>
        </div>

        <nav class="sidebar-nav" id="sidebarNav">
            {sidebar_nav_html}
        </nav>

        <div class="sidebar-footer">
            <a href="/index.html" class="ext-link">FnBOps Portal</a>
            <button class="theme-toggle-btn" onclick="toggleTheme()">Theme: <span id="themeLabel">Dark</span></button>
        </div>
    </aside>

    <div style="flex: 1; display: flex; flex-direction: column;">
        <header class="mobile-header">
            <button class="theme-toggle-btn" onclick="toggleSidebar()">Menu</button>
            <span style="font-weight: 600; font-size: 0.95rem;">WFM SOP</span>
            <button class="theme-toggle-btn" onclick="toggleTheme()">Theme</button>
        </header>

        <main id="main">
            <div class="main-inner">
                {content_sections_html}
            </div>
        </main>
    </div>

    <script>
        function switchDoc(id) {{
            // Hide all
            document.querySelectorAll('.doc-section').forEach(sec => sec.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(btn => btn.classList.remove('active'));

            const targetSection = document.getElementById('doc-' + id);
            const targetBtn = document.querySelector('.nav-item[data-id="' + id + '"]');

            if (targetSection) {{
                targetSection.classList.add('active');
                window.location.hash = '#' + id;
                window.scrollTo({{ top: 0, behavior: 'smooth' }});
            }}
            if (targetBtn) {{
                targetBtn.classList.add('active');
            }}

            // Close mobile sidebar if open
            if (window.innerWidth <= 900) {{
                document.getElementById('sidebar').classList.remove('open');
                document.getElementById('backdrop').classList.remove('open');
            }}
        }}

        function toggleSidebar() {{
            const sidebar = document.getElementById('sidebar');
            const backdrop = document.getElementById('backdrop');
            sidebar.classList.toggle('open');
            backdrop.classList.toggle('open');
        }}

        function toggleTheme() {{
            const current = document.documentElement.getAttribute('data-theme');
            const next = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            document.getElementById('themeLabel').innerText = next === 'dark' ? 'Dark' : 'Light';
            localStorage.setItem('wfm_sop_theme', next);
        }}

        function handleSearch(query) {{
            const q = query.trim().toLowerCase();
            document.querySelectorAll('.nav-item').forEach(btn => {{
                const title = btn.querySelector('.nav-item-title').innerText.toLowerCase();
                const id = btn.getAttribute('data-id');
                const sec = document.getElementById('doc-' + id);
                const content = sec ? sec.innerText.toLowerCase() : '';

                if (!q || title.includes(q) || content.includes(q)) {{
                    btn.style.display = 'flex';
                }} else {{
                    btn.style.display = 'none';
                }}
            }});
        }}

        // Init on load
        window.addEventListener('DOMContentLoaded', () => {{
            const savedTheme = localStorage.getItem('wfm_sop_theme') || 'dark';
            document.documentElement.setAttribute('data-theme', savedTheme);
            document.getElementById('themeLabel').innerText = savedTheme === 'dark' ? 'Dark' : 'Light';

            const hash = window.location.hash.replace('#', '');
            if (hash && document.getElementById('doc-' + hash)) {{
                switchDoc(hash);
            }} else {{
                switchDoc('tong-quan');
            }}
        }});
    </script>
</body>
</html>
'''

output_path = os.path.join(sop_dir, "index.html")
with open(output_path, "w", encoding="utf-8") as f:
    f.write(template)

print("Generated standalone premium index.html successfully at:", output_path)
