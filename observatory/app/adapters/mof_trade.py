"""Adapter: semiconductor trade — Japan exports and imports by partner country.

Source: the Ministry of Finance *Trade Statistics of Japan*, principal-commodity
by country tables (普通貿易統計 概況品別国別表), served through the e-Stat API.
Monthly quantity and value for every partner country, from January 2001.

Why this table and not the industrial production indices: it is the only
semiconductor-related series on e-Stat that is actually current (the 2020-base
IIP tables stopped at March 2026 and were last updated in June), and it is the
only one published in explicit revision stages — 速報 → 確報 → 確々報 → 確定.
Those stages are vintages in the source's own vocabulary, which is why this
dataset earns its place: the point-in-time history it accumulates cannot be
bought or back-filled later.

Data facts the parser and the gates depend on:

- **Commodity codes are direction-specific.** `70311000` means 半導体等電子部品
  (semiconductors and electronic components) on the import side and 音響機器
  (audio equipment) on the export side. A shared code map would silently chart
  loudspeakers as chips. Exports and imports therefore carry separate maps.
- **The month lives in the classification, not the time axis.** `@time` is the
  year; `cat02` carries Unit, year totals, and then quantity/value per calendar
  month (130/140 = January, stepping by 20).
- **Uncovered months are published as 0, not as blanks.** The 2026 table
  returns zeros for August through December. Storing those would put a
  fabricated zero on every chart, so coverage is derived per year as the last
  month carrying any non-zero value anywhere in the slice, and later months are
  dropped. Zeros *inside* the covered window are real — they mean no trade
  recorded with that partner that month — and are kept.
- **Value is in thousands of yen** (the API tags it 千円); quantity is in a
  per-commodity unit (number, kilograms) that the table publishes in `cat02`
  code 100.
- e-Stat serves the whole classification in English (`lang=E`) — the official
  country and commodity names — so nothing here is transliterated by hand.

History is fetched in year-blocks. Blocks that the Ministry has closed
(確定) never change again, so each table is cached on the data volume under
the publisher's own `UPDATED_DATE`: a routine run re-downloads only the
current year, and a boot after a redeploy costs one API call per table
instead of five minutes of downloading.
"""
import datetime
import gzip
import json
import os
import pathlib
import re

from . import estat_api


class ValidationError(Exception):
    pass


# --- what we ingest ----------------------------------------------------------

# e-Stat statsDataId per year-block. Blocks before the current year are 確定
# (final) and stop changing; the current-year table is rewritten every month as
# the Ministry adds a month and firms up the ones before it.
#
# History starts at 2001. The Ministry publishes the same tables back to 1988
# (0003258349/50/51 exports, 0003258352/53/54 imports) — adding them is a
# one-off backfill, deliberately left out of the routine ingest so that a boot
# against an empty volume cannot outrun the platform's health-check window.
TABLES = [
    ("0003228190", "exp", "2001-2005"),
    ("0003228191", "exp", "2006-2010"),
    ("0003228192", "exp", "2011-2015"),
    ("0003313967", "exp", "2016-2020"),
    ("0003425295", "exp", "2021-2025"),
    ("0004049327", "exp", "2026-"),
    ("0003228197", "imp", "2001-2005"),
    ("0003228198", "imp", "2006-2010"),
    ("0003228199", "imp", "2011-2015"),
    ("0003313968", "imp", "2016-2020"),
    ("0003425296", "imp", "2021-2025"),
    ("0004049328", "imp", "2026-"),
]

# (code, English label, Japanese label, sort order, level, chart label).
# English names are ours,
# not e-Stat's: the API serves them upper-cased ("SEMICON MACHINERY ETC"),
# which is a shout on every axis label and every CSV header.
#
# Level-3 codes are the published parents; the level-4 codes beneath them are
# their components. A parent is NOT the sum of the components listed here —
# the Ministry publishes other children we do not carry — so the two levels
# must never be added together.
COMMODITIES = {
    "exp": [
        ("70323000", "Semiconductors & electronic components", "半導体等電子部品", 0, "group",
         "Semiconductors & components"),
        ("70323050", "Integrated circuits", "ＩＣ", 1, "item", "Integrated circuits"),
        ("70323030", "Discrete semiconductors", "個別半導体", 2, "item", "Discrete semis"),
        ("70323010", "Thermionic tubes", "熱電子管", 3, "item", "Thermionic tubes"),
        ("70131000", "Semiconductor machinery & equipment", "半導体等製造装置", 4, "group",
         "Chipmaking equipment etc."),
        ("70131010", "Semiconductor manufacturing equipment", "半導体製造装置", 5, "item",
         "Chipmaking equipment"),
    ],
    "imp": [
        ("70311000", "Semiconductors & electronic components", "半導体等電子部品", 0, "group",
         "Semiconductors & components"),
        ("70311030", "Integrated circuits", "ＩＣ", 1, "item", "Integrated circuits"),
        ("70311010", "Transistors & diodes", "トランジスター等", 2, "item", "Transistors & diodes"),
        ("70131000", "Semiconductor machinery & equipment", "半導体等製造装置", 4, "group",
         "Chipmaking equipment etc."),
        ("70131010", "Semiconductor manufacturing equipment", "半導体製造装置", 5, "item",
         "Chipmaking equipment"),
    ],
}

# Partner countries, as the Ministry codes and names them (e-Stat area codes:
# the Ministry's own country code prefixed with 50). Held here rather than read
# from the metadata on every ingest for the same reason jnto_visitors holds its
# markets: a name the source revises must not silently rewrite the history we
# have already published under the old one, and an English label belongs in the
# product's voice, not in whatever case the API happens to return it.
#
# The third digit is the Ministry's region: 1 Asia (including the Middle East
# and Central Asia), 2 Europe, 3 North America, 4 South America, 5 Africa,
# 6 Oceania, 7 special entries that are not countries at all.
REGIONS = [
    ("1", "Asia & Middle East"),
    ("2", "Europe"),
    ("3", "North America"),
    ("4", "South America"),
    ("5", "Africa"),
    ("6", "Oceania"),
    ("7", "Special"),
]
REGION_LABEL = dict(REGIONS)

PARTNERS = [
    ("50103", "Republic of Korea", "大韓民国"),
    ("50104", "North Korea", "北朝鮮"),
    ("50105", "People's Republic of China", "中華人民共和国"),
    ("50106", "Taiwan", "台湾"),
    ("50107", "Mongolia", "モンゴル"),
    ("50108", "Hong Kong", "香港"),
    ("50110", "Viet Nam", "ベトナム"),
    ("50111", "Thailand", "タイ"),
    ("50112", "Singapore", "シンガポール"),
    ("50113", "Malaysia", "マレーシア"),
    ("50116", "Brunei", "ブルネイ"),
    ("50117", "Philippines", "フィリピン"),
    ("50118", "Indonesia", "インドネシア"),
    ("50120", "Cambodia", "カンボジア"),
    ("50121", "Laos", "ラオス"),
    ("50122", "Myanmar", "ミャンマー"),
    ("50123", "India", "インド"),
    ("50124", "Pakistan", "パキスタン"),
    ("50125", "Sri Lanka", "スリランカ"),
    ("50126", "Maldives", "モルディブ"),
    ("50127", "Bangladesh", "バングラデシュ"),
    ("50128", "Timor-Leste", "東ティモール"),
    ("50129", "Macao", "マカオ"),
    ("50130", "Afghanistan", "アフガニスタン"),
    ("50131", "Nepal", "ネパール"),
    ("50132", "Bhutan", "ブータン"),
    ("50133", "Iran", "イラン"),
    ("50134", "Iraq", "イラク"),
    ("50135", "Bahrain", "バーレーン"),
    ("50137", "Saudi Arabia", "サウジアラビア"),
    ("50138", "Kuwait", "クウェート"),
    ("50140", "Qatar", "カタール"),
    ("50141", "Oman", "オマーン"),
    ("50143", "Israel", "イスラエル"),
    ("50144", "Jordan", "ヨルダン"),
    ("50145", "Syria", "シリア"),
    ("50146", "Lebanon", "レバノン"),
    ("50147", "United Arab Emirates", "アラブ首長国連邦"),
    ("50149", "Yemen", "イエメン"),
    ("50150", "Azerbaijan", "アゼルバイジャン"),
    ("50151", "Armenia", "アルメニア"),
    ("50152", "Uzbekistan", "ウズベキスタン"),
    ("50153", "Kazakhstan", "カザフスタン"),
    ("50154", "Kyrgyz", "キルギス"),
    ("50155", "Tajikistan", "タジキスタン"),
    ("50156", "Turkmenistan", "トルクメニスタン"),
    ("50157", "Georgia", "ジョージア"),
    ("50158", "The West Bank and Gaza Strip", "ヨルダン川西岸及びガザ"),
    ("50201", "Iceland", "アイスランド"),
    ("50202", "Norway", "ノルウェー"),
    ("50203", "Sweden", "スウェーデン"),
    ("50204", "Denmark", "デンマーク"),
    ("50205", "United Kingdom", "英国"),
    ("50206", "Ireland", "アイルランド"),
    ("50207", "Netherlands", "オランダ"),
    ("50208", "Belgium", "ベルギー"),
    ("50209", "Luxembourg", "ルクセンブルク"),
    ("50210", "France", "フランス"),
    ("50211", "Monaco", "モナコ"),
    ("50212", "Andorra", "アンドラ"),
    ("50213", "Germany", "ドイツ"),
    ("50215", "Switzerland", "スイス"),
    ("50216", "Azores (Portugal)", "アゾレス(葡)"),
    ("50217", "Portugal", "ポルトガル"),
    ("50218", "Spain", "スペイン"),
    ("50219", "Gibraltar (UK)", "ジブラルタル(英)"),
    ("50220", "Italy", "イタリア"),
    ("50221", "Malta", "マルタ"),
    ("50222", "Finland", "フィンランド"),
    ("50223", "Poland", "ポーランド"),
    ("50224", "Russia", "ロシア"),
    ("50225", "Austria", "オーストリア"),
    ("50227", "Hungary", "ハンガリー"),
    ("50228", "Serbia", "セルビア"),
    ("50229", "Albania", "アルバニア"),
    ("50230", "Greece", "ギリシャ"),
    ("50231", "Romania", "ルーマニア"),
    ("50232", "Bulgaria", "ブルガリア"),
    ("50233", "Cyprus", "キプロス"),
    ("50234", "Turkey", "トルコ"),
    ("50235", "Estonia", "エストニア"),
    ("50236", "Latvia", "ラトビア"),
    ("50237", "Lithuania", "リトアニア"),
    ("50238", "Ukraine", "ウクライナ"),
    ("50239", "Belarus", "ベラルーシ"),
    ("50240", "Moldova", "モルドバ"),
    ("50241", "Croatia", "クロアチア"),
    ("50242", "Slovenia", "スロベニア"),
    ("50243", "Bosnia and Herzegovina", "ボスニア・ヘルツェゴビナ"),
    ("50244", "North Macedonia", "北マケドニア"),
    ("50245", "Czech Republic", "チェコ"),
    ("50246", "Slovakia", "スロバキア"),
    ("50247", "Montenegro", "モンテネグロ"),
    ("50248", "Kosovo", "コソボ"),
    ("50249", "Faroe Islands (Denmark)", "フェロー諸島（デンマーク）"),
    ("50250", "Vatican City", "バチカン"),
    ("50301", "Greenland (Denmark)", "グリーンランド(デンマーク)"),
    ("50302", "Canada", "カナダ"),
    ("50303", "St.Pierre and Miquelon (France)", "サンピエール及びミクロン(仏)"),
    ("50304", "United States of America", "アメリカ合衆国"),
    ("50305", "Mexico", "メキシコ"),
    ("50306", "Guatemala", "グアテマラ"),
    ("50307", "Honduras", "ホンジュラス"),
    ("50308", "Belize", "ベリーズ"),
    ("50309", "El Salvador", "エルサルバドル"),
    ("50310", "Nicaragua", "ニカラグア"),
    ("50311", "Costa Rica", "コスタリカ"),
    ("50312", "Panama", "パナマ"),
    ("50314", "Bermuda (UK)", "バーミュダ(英)"),
    ("50315", "The Bahamas", "バハマ"),
    ("50316", "Jamaica", "ジャマイカ"),
    ("50317", "Turks, and Caicos Islands (UK)", "タークス及びカイコス諸島(英)"),
    ("50319", "Barbados", "バルバドス"),
    ("50320", "Trinidad and Tobago", "トリニダード・トバゴ"),
    ("50321", "Cuba", "キューバ"),
    ("50322", "Haiti", "ハイチ"),
    ("50323", "Dominican Republic", "ドミニカ共和国"),
    ("50324", "Puerto Rico (USA)", "プエルトリコ(米)"),
    ("50325", "US Virgin Islands", "米領バージン諸島"),
    ("50326", "Netherlands Antilles", "蘭領アンティール"),
    ("50327", "French West Indies", "仏領西インド諸島"),
    ("50328", "Cayman islands (UK)", "ケイマン諸島(英)"),
    ("50329", "Grenada", "グレナダ"),
    ("50330", "St.Lucia", "セントルシア"),
    ("50331", "Antigua and Barbuda", "アンティグア・バーブーダ"),
    ("50332", "British Virgin Islands", "英領バージン諸島"),
    ("50333", "Dominica", "ドミニカ"),
    ("50334", "Monstserrat (UK)", "モントセラト(英)"),
    ("50335", "St.Christopher and Nevis", "セントクリストファー・ネービス"),
    ("50336", "St.Vincent", "セントビンセント"),
    ("50337", "British Anguilla", "英領アンギラ"),
    ("50338", "St.Barthelemy (France)", "サン・バルテルミー島（仏）"),
    ("50401", "Colombia", "コロンビア"),
    ("50402", "Venezuela", "ベネズエラ"),
    ("50403", "Guyana", "ガイアナ"),
    ("50404", "Suriname", "スリナム"),
    ("50405", "French Guiana", "仏領ギアナ"),
    ("50406", "Ecuador", "エクアドル"),
    ("50407", "Peru", "ペルー"),
    ("50408", "Bolivia", "ボリビア"),
    ("50409", "Chile", "チリ"),
    ("50410", "Brazil", "ブラジル"),
    ("50411", "Paraguay", "パラグアイ"),
    ("50412", "Uruguay", "ウルグアイ"),
    ("50413", "Argentina", "アルゼンチン"),
    ("50414", "Falkland Islands and Dependencies (UK)", "フォークランド諸島及びその附属諸島（英）"),
    ("50415", "British Antarctic Territory", "英領南極地域"),
    ("50501", "Morocco", "モロッコ"),
    ("50502", "Ceuta and Melilla (Spain)", "セウタ及びメリリア(西)"),
    ("50503", "Algeria", "アルジェリア"),
    ("50504", "Tunisia", "チュニジア"),
    ("50505", "Libya", "リビア"),
    ("50506", "Egypt", "エジプト"),
    ("50507", "Sudan", "スーダン"),
    ("50508", "West Sahara", "西サハラ"),
    ("50509", "Mauritania", "モーリタニア"),
    ("50510", "Senegal", "セネガル"),
    ("50511", "The Gambia", "ガンビア"),
    ("50512", "Guinea-Bissau", "ギニア・ビサウ"),
    ("50513", "Guinea", "ギニア"),
    ("50514", "Sierra Leone", "シエラレオネ"),
    ("50515", "Liberia", "リベリア"),
    ("50516", "Rep. of Cote d'Ivoire", "コートジボワール"),
    ("50517", "Ghana", "ガーナ"),
    ("50518", "Togo", "トーゴ"),
    ("50519", "Benin", "ベナン"),
    ("50520", "Mali", "マリ"),
    ("50521", "Burkina Faso", "ブルキナファソ"),
    ("50522", "Cape Verde", "カーボベルデ"),
    ("50523", "Canary Islands (Spain)", "カナリー諸島(西)"),
    ("50524", "Nigeria", "ナイジェリア"),
    ("50525", "Niger", "ニジェール"),
    ("50526", "Rwanda", "ルワンダ"),
    ("50527", "Cameroon", "カメルーン"),
    ("50528", "Chad", "チャド"),
    ("50529", "Central Africa", "中央アフリカ"),
    ("50530", "Equatorial Guinea", "赤道ギニア"),
    ("50531", "Gabon", "ガボン"),
    ("50532", "Republic of Congo", "コンゴ共和国"),
    ("50533", "Democratic Republic of Congo", "コンゴ民主共和国"),
    ("50534", "Burundi", "ブルンジ"),
    ("50535", "Angola", "アンゴラ"),
    ("50536", "Sao Tome and Principe", "サントメ・プリンシペ"),
    ("50537", "St. Helena Island and Dependencies (UK)", "セントヘレナ及びその附属諸島(英)"),
    ("50538", "Ethiopia", "エチオピア"),
    ("50539", "Djibouti", "ジブチ"),
    ("50540", "Somalia", "ソマリア"),
    ("50541", "Kenya", "ケニア"),
    ("50542", "Uganda", "ウガンダ"),
    ("50543", "Tanzania", "タンザニア"),
    ("50544", "Seychelles", "セーシェル"),
    ("50545", "Mozambique", "モザンビーク"),
    ("50546", "Madagascar", "マダガスカル"),
    ("50547", "Mauritius", "モーリシャス"),
    ("50548", "Reunion (France)", "レユニオン(仏)"),
    ("50549", "Zimbabwe", "ジンバブエ"),
    ("50550", "Namibia", "ナミビア"),
    ("50551", "South Africa", "南アフリカ共和国"),
    ("50552", "Lesotho", "レソト"),
    ("50553", "Malawi", "マラウイ"),
    ("50554", "Zambia", "ザンビア"),
    ("50555", "Botswana", "ボツワナ"),
    ("50556", "Eswatini", "エスワティニ"),
    ("50557", "British indian Ocean Territories", "英領インド洋地域"),
    ("50558", "Comoros", "コモロ"),
    ("50559", "Eritrea", "エリトリア"),
    ("50560", "Republic of South Sudan", "南スーダン"),
    ("50601", "Australia", "オーストラリア"),
    ("50602", "Papua New Guinea", "パプアニューギニア"),
    ("50605", "Other Australian Territories", "その他のオーストラリア領"),
    ("50606", "New Zealand", "ニュージーランド"),
    ("50607", "Cook", "クック"),
    ("50608", "Tokelau Islands (NZ)", "トケラウ諸島(ニュージーランド)"),
    ("50609", "Niue", "ニウエ"),
    ("50610", "Samoa", "サモア"),
    ("50611", "Vanuatu", "バヌアツ"),
    ("50612", "Fiji", "フィジー"),
    ("50613", "Solomon Islands", "ソロモン"),
    ("50614", "Tonga", "トンガ"),
    ("50615", "Kiribati", "キリバス"),
    ("50616", "Pitcairn (UK)", "ピットケルン(英)"),
    ("50617", "Nauru", "ナウル"),
    ("50618", "New Caledonia (France)", "ニューカレドニア(仏)"),
    ("50619", "French Polynesia", "仏領ポリネシア"),
    ("50620", "Guam (USA)", "グアム(米)"),
    ("50621", "American Samoa", "米領サモア"),
    ("50622", "American Oceania", "米領オセアニア"),
    ("50624", "Tuvalu", "ツバル"),
    ("50625", "Marshall", "マーシャル"),
    ("50626", "Micronesia", "ミクロネシア"),
    ("50627", "Northern Mariana Islands (USA)", "北マリアナ諸島(米)"),
    ("50628", "Palau", "パラオ"),
    ("50701", "For Order", "指図式"),
    ("50702", "Unknown", "不明"),
    ("50703", "Bonded Manufacturing Warehouse,Integrated Hozei Area", "保税工場・総合保税地域"),
]
PARTNER_EN = dict((c, en) for c, en, _ja in PARTNERS)
PARTNER_JA = dict((c, ja) for c, _en, ja in PARTNERS)


def partner_region(code):
    return code[2] if len(code) > 2 else "7"


FLOW_LABEL = {"exp": "exports", "imp": "imports"}
FLOW_PREP = {"exp": "to", "imp": "from"}

# cat02: 100 is the quantity unit, 110/120 the year totals, then a
# quantity/value pair per calendar month starting at 130 and stepping by 20.
UNIT_FIELD = "100"
MONTH_FIELDS = dict(
    (str(130 + (m - 1) * 20), (m, "qty")) for m in range(1, 13))
MONTH_FIELDS.update(
    (str(140 + (m - 1) * 20), (m, "val")) for m in range(1, 13))

VALUE_UNIT = "jpy_1000"   # the API tags every value cell 千円

FIRST_YEAR = 2001


DATASET = {
    "slug": "trade-semis",
    "title": "Semiconductor Trade — Exports and Imports by Partner",
    "country": "Japan",
    "agency": "Ministry of Finance",
    "agency_ja": "財務省",
    "base": None,
    "frequency": "monthly",
    "description": (
        "Monthly Japanese trade in semiconductors, semiconductor components "
        "and semiconductor manufacturing equipment, by partner country, from "
        "January 2001. Value in thousands of yen and quantity in the "
        "commodity's published unit, exactly as released by the Ministry of "
        "Finance in the principal-commodity by country tables of the Trade "
        "Statistics of Japan. Export and import commodity classifications are "
        "separate and their codes do not correspond."
    ),
}

SOURCE = {
    "source_id": "estat:00350300:gaikyohin-semis",
    "name": ("Ministry of Finance — Trade Statistics of Japan, principal "
             "commodity by country tables (semiconductor commodities)"),
    "name_ja": "財務省 普通貿易統計 概況品別国別表（半導体関連品目）",
    "url": "https://www.customs.go.jp/toukei/info/index_e.htm",
    "license_note": (
        "Government of Japan Standard Terms of Use (compatible with CC BY "
        "4.0): free to use with attribution to the Ministry of Finance. "
        "Retrieved through the e-Stat API (統計データの自動取得), which "
        "requires a free application ID. Figures pass through published "
        "revision stages — preliminary (速報), confirmed (確報), revised "
        "(確々報) and final (確定); each stage is stored here as its own "
        "vintage."
    ),
}

DOWNLOAD_URL = ("https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"
                " (普通貿易統計 概況品別国別表)")

RAW_SUFFIX = ".json.gz"


# --- fetch -------------------------------------------------------------------

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "data" / "cache" / "mof-trade"

# Which tables to look up, and the statistic they belong to.
STATS_CODE = "00350300"      # 普通貿易統計
LIST_SEARCH = "概況品別国別表"


def _updated_dates():
    """{statsDataId: UPDATED_DATE} for the tables we ingest.

    The Ministry's own publication stamp is the cache key: a table whose stamp
    has not moved cannot have changed, and one whose stamp has moved must be
    re-read even if we already hold a copy.
    """
    payload = estat_api.call("getStatsList", statsCode=STATS_CODE,
                             searchWord=LIST_SEARCH, limit=200)
    listing = payload["GET_STATS_LIST"]["DATALIST_INF"]["TABLE_INF"]
    if isinstance(listing, dict):
        listing = [listing]
    stamps = dict((t["@id"], str(t.get("UPDATED_DATE"))) for t in listing)
    missing = [tid for tid, _flow, _era in TABLES if tid not in stamps]
    if missing:
        raise estat_api.ApiError(
            "e-Stat no longer lists table(s) %s under %s — the Ministry has "
            "re-published the series under new ids and the adapter needs "
            "updating" % (", ".join(missing), STATS_CODE))
    return stamps


def _cached(table_id, stamp, kind, produce):
    """Read one piece of one table, from the volume if the stamp still matches.

    Cache misses for a stamp we do not hold are the only network traffic a
    routine run makes beyond the table listing. Stale entries for the same
    table are removed, so the cache tracks the published history rather than
    accumulating every stage a table ever passed through.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^0-9A-Za-z-]", "", stamp)
    path = CACHE_DIR / ("%s-%s-%s.json.gz" % (table_id, safe, kind))
    if path.exists():
        try:
            return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        except (OSError, ValueError, EOFError):
            pass       # a truncated cache file is re-fetched, never fatal
    value = produce()
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(
        json.dumps(value, sort_keys=True).encode("utf-8"), 6, mtime=0))
    os.replace(str(tmp), str(path))
    for old in CACHE_DIR.glob("%s-*-%s.json.gz" % (table_id, kind)):
        if old != path:
            try:
                old.unlink()
            except OSError:
                pass
    return value


def _table_payload(table_id, flow, stamp):
    codes = ",".join(c for c, _e, _j, _o, _k, _s in COMMODITIES[flow])

    def data():
        return estat_api.strip_timestamps(estat_api.get_stats_data(
            table_id, cdCat01=codes, metaGetFlg="N"))

    def meta(lang):
        params = {"statsDataId": table_id}
        if lang != "J":
            params["lang"] = lang
        return estat_api.strip_timestamps(
            estat_api.call("getMetaInfo", **params))

    return {
        "id": table_id, "flow": flow, "updated": stamp,
        "data": _cached(table_id, stamp, "data", data),
        "meta_ja": _cached(table_id, stamp, "metaJ", lambda: meta("J")),
        "meta_en": _cached(table_id, stamp, "metaE", lambda: meta("E")),
    }


def fetch():
    """Every year-block, in one deterministic gzipped envelope.

    Timestamps are stripped from each API response, so two runs against an
    unchanged upstream produce identical bytes and the runner's plain SHA-256
    comparison gives idempotency without a canonical_bytes() hook.
    """
    stamps = _updated_dates()
    envelope = {"tables": [_table_payload(tid, flow, stamps[tid])
                           for tid, flow, _era in TABLES]}
    return gzip.compress(
        json.dumps(envelope, sort_keys=True, ensure_ascii=False).encode("utf-8"),
        6, mtime=0)


# --- parse -------------------------------------------------------------------

def series_code(flow, commodity, area, measure):
    return "%s.%s.%s.%s" % (flow, commodity, area, measure)


def _class_names(meta_payload, class_id):
    """{code: name} for one axis of a getMetaInfo response.

    e-Stat prefixes the Japanese label with the Ministry's own numeric code
    ("105_中華人民共和国") and the English label without it. The prefix is
    stripped so a partner PARTNERS does not yet name still reads as a place
    rather than as a code glued to one.
    """
    objs = meta_payload["GET_META_INFO"]["METADATA_INF"]["CLASS_INF"]["CLASS_OBJ"]
    for obj in objs:
        if obj["@id"] != class_id:
            continue
        entries = obj["CLASS"]
        if isinstance(entries, dict):
            entries = [entries]
        return dict((e["@code"], re.sub(r"^\d+_", "", e["@name"]))
                    for e in entries)
    return {}


def _values_of(pages):
    for page in pages:
        block = page["GET_STATS_DATA"]["STATISTICAL_DATA"]["DATA_INF"].get("VALUE", [])
        if isinstance(block, dict):
            block = [block]
        for cell in block:
            yield cell


def _number(text):
    """A published cell as a float, or None when it carries no number.

    '-' and '' are missing. '***' is a figure the Ministry withholds for
    confidentiality — also missing, and emphatically not zero.
    """
    text = (text or "").strip()
    if not text or text in ("-", "－", "***", "X", "x"):
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def parse(raw_bytes):
    envelope = json.loads(gzip.decompress(raw_bytes).decode("utf-8"))

    # Names, newest table last so the current classification wins a tie.
    area_en, area_ja = {}, {}
    qty_unit = {}                       # (flow, commodity) -> published unit
    # (flow, commodity, area, measure) -> {(year, month): value}
    cells = {}
    # (flow, year) -> highest month carrying any non-zero value
    covered = {}

    for table in envelope["tables"]:
        flow = table["flow"]
        area_en.update(_class_names(table["meta_en"], "area"))
        area_ja.update(_class_names(table["meta_ja"], "area"))
        known = set(c for c, _e, _j, _o, _k, _s in COMMODITIES[flow])

        for cell in _values_of(table["data"]):
            commodity = cell["@cat01"]
            if commodity not in known:
                raise ValidationError(
                    "table %s returned commodity %s, which was not requested"
                    % (table["id"], commodity))
            field = cell["@cat02"]
            year = int(str(cell["@time"])[:4])

            if field == UNIT_FIELD:
                unit = (cell.get("$") or "").strip()
                if unit:
                    qty_unit.setdefault((flow, commodity), unit)
                continue
            slot = MONTH_FIELDS.get(field)
            if slot is None:
                continue                # year totals: recomputable, not stored
            month, measure = slot
            value = _number(cell.get("$"))
            if value is None:
                continue
            if value:
                key = (flow, year)
                if month > covered.get(key, 0):
                    covered[key] = month
            area = cell["@area"]
            cells.setdefault((flow, commodity, area, measure), {})[(year, month)] = value

    if not covered:
        raise ValidationError("no non-zero values in any table")

    # Series, in a fixed order that does not move when trade does: flow, then
    # the commodity order declared above, then the partner's published code.
    areas = sorted(set(k[2] for k in cells))
    area_pos = dict((code, i) for i, code in enumerate(areas))

    series, observations = [], []
    for flow in ("exp", "imp"):
        for commodity, name_en, name_ja, order, _kind, _short in COMMODITIES[flow]:
            unit_q = qty_unit.get((flow, commodity))
            for area in areas:
                for measure in ("val", "qty"):
                    got = cells.get((flow, commodity, area, measure))
                    if not got:
                        continue
                    points = []
                    for (year, month), value in got.items():
                        if month > covered.get((flow, year), 0):
                            continue    # a month the table has not reached
                        points.append((datetime.date(year, month, 1), value))
                    # A partner with no trade at all in this commodity would
                    # otherwise contribute 25 years of zeros to every payload.
                    if not any(v for _p, v in points):
                        continue
                    code = series_code(flow, commodity, area, measure)
                    series.append({
                        "code": code,
                        "name_en": "%s — %s %s %s (%s)" % (
                            name_en, FLOW_LABEL[flow], FLOW_PREP[flow],
                            PARTNER_EN.get(area) or area_en.get(area, area),
                            "value" if measure == "val" else "quantity"),
                        "name_ja": "%s 対%s%s（%s）" % (
                            name_ja,
                            PARTNER_JA.get(area) or area_ja.get(area, area),
                            "輸出" if flow == "exp" else "輸入",
                            "金額" if measure == "val" else "数量"),
                        "unit": VALUE_UNIT if measure == "val" else (unit_q or "unit"),
                        "weight_per_10000": None,   # meaningless for a trade flow
                        "sort_order": (0 if flow == "exp" else 1) * 1000000
                                      + order * 100000
                                      + area_pos[area] * 2
                                      + (0 if measure == "val" else 1),
                    })
                    for period, value in sorted(points):
                        observations.append(
                            {"code": code, "period": period, "value": value})

    return series, observations


# --- validate ----------------------------------------------------------------

# The Ministry has never published a negative figure in these tables: a value
# is a customs-declared amount and a quantity a physical count.
MIN_OBSERVATIONS = 200_000

# The partners that must be present for the flagship commodity in the latest
# month, in every plausible state of the world. If Japan stops shipping chips
# to Taiwan we have a parsing fault, not a trade story.
ANCHOR_PARTNERS = {"exp": ("50106", "50105"),      # Taiwan, China
                   "imp": ("50106", "50304")}      # Taiwan, United States
FLAGSHIP = {"exp": "70323050", "imp": "70311030"}  # integrated circuits


def validate(series, observations):
    codes = set(s["code"] for s in series)
    if not codes:
        raise ValidationError("no series parsed")

    if len(observations) < MIN_OBSERVATIONS:
        raise ValidationError(
            "only %d observations parsed, expected at least %d — a year-block "
            "probably came back empty" % (len(observations), MIN_OBSERVATIONS))

    seen = set()
    periods = set()
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        periods.add(o["period"])
        if o["value"] < 0:
            raise ValidationError(
                "%s %s: negative value %s — trade values and quantities are "
                "customs-declared amounts and never go below zero"
                % (o["code"], o["period"], o["value"]))

    ordered = sorted(periods)
    if ordered[0] != datetime.date(FIRST_YEAR, 1, 1):
        raise ValidationError(
            "history starts %s, expected %s-01 — the earliest year-block is "
            "missing" % (ordered[0], FIRST_YEAR))

    # Every month between the first and the last must exist: a hole means a
    # year-block failed to parse and the gap would read as an absence of trade.
    expected = []
    y, m = FIRST_YEAR, 1
    while datetime.date(y, m, 1) <= ordered[-1]:
        expected.append(datetime.date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    holes = sorted(set(expected) - periods)
    if holes:
        raise ValidationError(
            "%d months missing between %s and %s, e.g. %s"
            % (len(holes), ordered[0], ordered[-1], holes[0]))

    latest = ordered[-1]
    today = datetime.date.today()
    if latest > today:
        raise ValidationError("latest month %s is in the future" % latest)
    if (today - latest).days > 200:
        raise ValidationError(
            "latest month %s is implausibly old for a changed table" % latest)

    # Both directions must have arrived, and the flagship commodity must reach
    # its anchor partners in the newest month.
    latest_codes = set(o["code"] for o in observations if o["period"] == latest)
    for flow in ("exp", "imp"):
        if not any(c.startswith(flow + ".") for c in latest_codes):
            raise ValidationError(
                "no %s data in the latest month %s" % (FLOW_LABEL[flow], latest))
        for partner in ANCHOR_PARTNERS[flow]:
            code = series_code(flow, FLAGSHIP[flow], partner, "val")
            if code not in latest_codes:
                raise ValidationError(
                    "no integrated-circuit %s value for partner %s in %s"
                    % (FLOW_LABEL[flow], partner, latest))

    partners = set(c.split(".")[2] for c in codes)
    unnamed = sorted(p for p in partners if p not in PARTNER_EN)
    world = {}
    for o in observations:
        flow, commodity, _area, measure = o["code"].split(".")
        if measure == "val" and commodity == FLAGSHIP[flow]:
            world.setdefault(flow, {}).setdefault(o["period"], 0.0)
            world[flow][o["period"]] += o["value"]

    return {
        "series": len(series),
        "observations": len(observations),
        "months": len(ordered),
        "partners": len(partners),
        "partners_without_a_name": unnamed,
        "latest_period": latest.isoformat(),
        "ic_exports_latest_jpy_1000": world.get("exp", {}).get(latest),
        "ic_imports_latest_jpy_1000": world.get("imp", {}).get(latest),
    }


# --- presentation ------------------------------------------------------------

# Why 100 days and not the 30-odd a monthly series usually gets: this table is
# published about two months in arrears (July data appeared on 28 August 2026)
# and then sits until the following month's update, so the newest month we
# serve is routinely 60 days old and reaches ~90 just before the next release.
# A tighter limit would cry stale every month of a perfectly healthy ingest.
PRESENTATION = {
    "credit_line": "Source: Ministry of Finance, Japan — Trade Statistics of Japan.",
    "stale_after_days": 100,
    "trade": {
        "flows": [
            {"key": "exp", "label": "Exports", "preposition": "to"},
            {"key": "imp", "label": "Imports", "preposition": "from"},
        ],
        "commodities": dict(
            (flow, [{"code": c, "label": e, "label_ja": j, "short": sh,
                     "level": k, "order": o}
                    for c, e, j, o, k, sh in COMMODITIES[flow]])
            for flow in COMMODITIES),
        "default_flow": "exp",
        "default_commodity": {"exp": "70323050", "imp": "70311030"},
        # The partners a semiconductor desk actually watches. Order is the
        # order they appear in the picker, not a ranking.
        "feature_partners": ["50105", "50106", "50103", "50108", "50304", "50112"],
        "value_unit": VALUE_UNIT,
    },
}
