"""Job titles (and the few place names) that a source writes in Chinese, Japanese or Korean, shown in English on the board.

english_title(title): the English title of the job -
  1. a title of TITLE_EN: its English translation (checked by hand: the job's own words, nothing added);
  2. a title that also carries its English name ("Sales Manager 業務經理", "ソリューションアーキテクト（Solution Architect）"): that English part,
     without the source's internal codes ("[DCJP] ...", "..._BCSC");
  3. else the title as the source wrote it (a new title in Chinese only: add it to TITLE_EN).
english_place(location): the same for a place name ("无锡, China" -> "Wuxi, China").
Pure python (no Odoo imports), shared by the model and the tests."""
import re
import unicodedata

# Chinese (Han), Japanese (kana) and Korean (Hangul) letters, and their punctuation
_CJK = r'　-〿぀-ヿ㐀-䶿一-鿿가-힯豈-﫿～・'
CJK = re.compile('[%s]' % _CJK)
_CJK_RUN = re.compile('[%s]+' % _CJK)
_CJK_GROUP = re.compile(r'[\(\[][^()\[\]]*[%s][^()\[\]]*[\)\]]' % _CJK)       # "(担当領域：製造業)", "[보쉬코리아]"
_LEAD_CODE = re.compile(r'^\s*\[[A-Za-z0-9 ]{1,12}\]\s*')                      # "[DCJP] ", "[GS]"
_TAIL_CODE = re.compile(r'_[A-Z]{2,6}\s*$')                                     # "_BCSC", "_DC"
_WORD = re.compile(r'[A-Za-z]{2,}')

# the titles of the jobs the sources have sent in Chinese / Japanese / Korean, translated by hand
TITLE_EN = {
    'AI与数据开发工程师_BCI': 'AI & Data Development Engineer',
    'Account Executive - Enterprise Sales (Japan)(担当領域：インターネットメディア)': 'Account Executive - Enterprise Sales (Japan) (Internet Media)',
    'Account Executive, Majors (製造業)': 'Account Executive, Majors (Manufacturing)',
    'GSI ソリューションアーキテクト (東京)': 'GSI Solutions Architect (Tokyo)',
    'Senior Account Executive - Enterprise Sales (Japan) (担当領域：大手SIer & 配信メディア)': 'Senior Account Executive - Enterprise Sales (Japan) (Major SIers & Streaming Media)',
    'Senior Account Executive - Enterprise Sales (Japan)(担当領域：製造・金融業界）': 'Senior Account Executive - Enterprise Sales (Japan) (Manufacturing & Finance)',
    'Senior People Operations Associate 資深人力資源專員(薪酬管理)': 'Senior People Operations Associate (Compensation)',
    'Senior Product Engineer - LT / 高级产品工程师-线性传动技术_DCCS': 'Senior Product Engineer - Linear Motion Technology',
    'VMC软件销售_VM': 'VMC Software Sales',
    '[DCJP] 産業機械用オートメーションソフトウェアの営業・事業開発': 'Sales & Business Development - Automation Software for Industrial Machinery',
    '[DCJP] 自動車製造向けFAソリューションの営業・事業開発（溶接・締付け技術）': 'Sales & Business Development - Factory Automation for Car Manufacturing (Welding & Fastening)',
    '[보쉬전장] 시니어 기술영업 엔지니어': 'Senior Technical Sales Engineer',
    'アカウントマネージャー（Account Manager ジュニア～ミッドレベル）': 'Account Manager (Junior to Mid-level)',
    'ゲームパブリッシング（日本市場）インターン': 'Game Publishing Intern (Japan Market)',
    'テクニカルアカウントマネージャー アーキテクト - 日本': 'Technical Account Manager Architect - Japan',
    'マーケティングプランナー': 'Marketing Planner',
    '传感器项目管理_VM': 'Sensor Project Manager',
    '供应商质量工程师PUQ Purchasing Quality': 'Supplier Quality Engineer (Purchasing Quality)',
    '减速器研发工程师_DC': 'Gear Reducer R&D Engineer',
    '减速机销售_DC': 'Gear Reducer Sales',
    '制造工艺技术员（智造菁英）_DCCB': 'Manufacturing Process Technician (Smart Manufacturing Talent Program)',
    '合规数据中心项目管理_XC': 'Compliance Data Center Project Manager',
    '嵌入式测试开发工程师（智能座舱/ADAS域控/家电域控)_BCSC': 'Embedded Test Development Engineer (Smart Cockpit / ADAS / Home Appliance Domain Controllers)',
    '工程信息系统（EIS）协调员_PT': 'Engineering Information Systems (EIS) Coordinator',
    '底盘域应用层软件开发工程师_BCSC': 'Chassis Domain Application Software Engineer',
    '座舱中间件开发工程师（AVM方向）_BCSC': 'Cockpit Middleware Development Engineer (AVM)',
    '感知模型剪枝量化工程师_XC': 'Perception Model Pruning & Quantization Engineer',
    '技术项目管理（底盘制动）_BCSC': 'Technical Project Manager (Chassis Braking)',
    '本地化（繁中）remote': 'Localization (Traditional Chinese) - Remote',
    '机械设计工程师 (非标设备)_SO': 'Mechanical Design Engineer (Non-standard Equipment)',
    '泊车建图定位算法工程师_XC': 'Parking Mapping & Localization Algorithm Engineer',
    '液压应用工程师_DCCS': 'Hydraulics Application Engineer',
    '电力电子硬件工程师_DCCX': 'Power Electronics Hardware Engineer',
    '电机机械设计工程师（标准设计平台）_EM': 'Electric Motor Mechanical Design Engineer (Standard Design Platform)',
    '电气设计工程师 (E-Plan)_BMG': 'Electrical Design Engineer (E-Plan)',
    '网络安全软件工程师_XC': 'Cybersecurity Software Engineer',
    '资深电机机械设计工程师（标准设计平台）_EM': 'Senior Electric Motor Mechanical Design Engineer (Standard Design Platform)',
    '销售(半导体客户）_DC': 'Sales (Semiconductor Customers)',
    '雷达天线工程师_XC': 'Radar Antenna Engineer',
    '项目采购工程师': 'Project Purchasing Engineer',
    '项目采购工程师（减速机）_DCCB': 'Project Purchasing Engineer (Gear Reducers)',
    '高级ADAS泊车HIL测试工程师_BCSC': 'Senior ADAS Parking HIL Test Engineer',
    '［ETAS］Solution Sales・Acquisition Manager': 'Solution Sales & Acquisition Manager (ETAS)',
}

PLACE_EN = {'无锡': 'Wuxi', '横浜市': 'Yokohama', '東京': 'Tokyo', '上海': 'Shanghai', '北京': 'Beijing', '深圳': 'Shenzhen', '苏州': 'Suzhou',
            '广州': 'Guangzhou', '杭州': 'Hangzhou', '南京': 'Nanjing', '成都': 'Chengdu', '武汉': 'Wuhan', '台北': 'Taipei', '香港': 'Hong Kong',
            '大阪': 'Osaka', '서울': 'Seoul'}


def has_cjk(text):
    return bool(CJK.search(text or ''))


def _tidy(text):
    text = re.sub(r'\(\s*\)|\[\s*\]', ' ', text)
    text = re.sub(r'\s*([/|·•_]|[-–—](?=\s|$))\s*(?=[/|·•_\-–—]|$)', ' ', text)          # separators left at the end / doubled
    text = re.sub(r'^[\s/|·•_\-–—:]+|[\s/|·•_\-–—:]+$', '', text)
    return re.sub(r'\s{2,}', ' ', text).strip()


def english_title(title):
    """The English title of a job (see the module doc); a title without Chinese / Japanese / Korean comes back unchanged."""
    raw = (title or '').strip()
    if not has_cjk(raw):
        return title
    if raw in TITLE_EN:
        return TITLE_EN[raw]
    text = unicodedata.normalize('NFKC', raw)                  # full-width "（）［］ＰＲ" -> "()[]PR"
    text = _CJK_GROUP.sub(' ', text)                            # a bracket of CJK words
    text = _LEAD_CODE.sub('', text)
    text = _CJK_RUN.sub(' ', text)
    text = _TAIL_CODE.sub('', _tidy(text))
    text = _tidy(re.sub(r'\(\s*([^()]*?)\s*\)', lambda m: '(%s)' % m.group(1) if m.group(1) else '', text))
    inner = re.fullmatch(r'(.*?)\s*\(([^()]+)\)', text)                 # "(Solution Architect)", "PR (PR Manager)": the English name in brackets
    if inner and len(_WORD.findall(inner.group(1))) < 2 and len(_WORD.findall(inner.group(2))) >= 2:
        text = inner.group(2).strip()
    if len(_WORD.findall(text)) >= 2 and not has_cjk(text):         # an English name of the job, not a lone code
        return text
    return title


def english_place(location):
    """A place name with the known Chinese / Japanese / Korean city names in English."""
    if not has_cjk(location):
        return location
    text = location
    for name, english in PLACE_EN.items():
        text = text.replace(name, english)
    return text
