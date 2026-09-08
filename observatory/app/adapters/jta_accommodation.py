"""Adapter: JTA Accommodation Survey — guest nights and room occupancy.

Source: the Japan Tourism Agency's 「宿泊旅行統計調査」, the only official
count of *nights actually slept* in Japan. JNTO tells us how many foreign
visitors crossed the border; this survey tells us where they slept, in what
kind of property, and how full it was. The two answer different questions and
are never added together.

Why this dataset is here, and what it is not
--------------------------------------------
Arrivals are a commoditised headline. Guest nights by prefecture, by visitor
nationality and by hotel type are not: they are Excel-only, Japanese-only, and
published across three release stages that nobody outside Japan reconciles.
This is the hotel and REIT layer of the inbound story, and the regional
dispersion layer that arrivals cannot give at all.

Measure types — two, and they must never be mixed:

- **person-nights** (`person_nights`) — a count of nights slept. Additive
  across areas and categories, never across the occupancy series.
- **percent** (`percent`) — an occupancy *rate*. A ratio: never summed, never
  weighted-averaged by us, only ever shown as published.

Both are official statistics exactly as the Agency published them. Every
growth rate, share, recovery index or nationality mix drawn from them is
derived and carries its formula, per the trust contract.

The three files this adapter reads, and why it needs all three
--------------------------------------------------------------
No single published file carries both history and detail, so the artifact is a
deterministic zip of three kinds of workbook, all discovered from the survey
page rather than hard-coded (every link is a rotating content id):

1. **推移表 — the trend workbook.** The history backbone: prefecture-level
   guest nights (total, Japanese, foreign) and prefecture x hotel-type room
   occupancy, monthly. Its "旧" sheets carry January 2011 to December 2025 and
   its current sheets carry 2026 onward. No other file gives more than a
   single year.
2. **年の確定値 集計結果 — the annual definitive workbooks**, one per year from
   FIRST_DETAIL_YEAR. Each holds twelve monthly sheets, and these are where the
   deep dimensions live with history: foreign guest nights by nationality,
   guest nights by hotel type, and the purpose and residence splits.
3. **第2次速報 — the monthly second-preliminary workbooks** for the months the
   annual definitive has not reached yet. Same table numbering as the annual
   file, plus the municipality tables that exist only in the new scheme.

Where two files carry the same (series, period) the more settled one wins:
monthly preliminary < trend < annual definitive. Overlaps are also *compared*,
and the agreement rate is reported in the validation summary — a free
cross-source check that would catch a misread column immediately.

The January 2026 break, which is real and is not smoothed over
---------------------------------------------------------------
From the January 2026 survey the Agency changed how it stratifies properties,
from **employee count** to **room count**, and widened the nationality list
from 21 categories to 24. The Agency itself keeps the two eras in separate
sheets rather than splicing them, and so do we:

- Facility-size series are published **from 2026 only**. The pre-2026
  employee-count bands measure a different thing and are deliberately not
  carried, because a single series that silently changes definition is worse
  than no series.
- The three nationality categories added in 2026 (Nordic region, Middle East,
  Mexico) begin in 2026. The residual "Other" is a *different residual* on
  either side of the break — before 2026 it still contained those three — so it
  is carried as two codes, `other-pre2026` and `other`, never as one.
- `PRESENTATION["break_period"]` names the boundary so every chart can mark it.

Reliability is published, and is worth more than it looks
----------------------------------------------------------
The survey is a sample, and unusually it publishes its own standard error rate
per prefecture per breakdown — from about 1% at the national headline to near
30% for the smallest properties in a thin prefecture. Individual cells also
carry an asterisk where the Agency flags them as weak. We keep the value and
record the flag rather than dropping it, and the count of flagged values is
reported on every release.

Missing is missing: a "-" cell is absent from the output, never a zero. This
matters more here than in most sources, because the municipality tables print
"-" wherever fewer than ten properties responded.

Obligation: the Agency's terms are the standard 政府標準利用規約 attribution —
the credit line is carried in PRESENTATION and rendered on the page and in
every export.
"""
import datetime
import io
import re
import urllib.request
import zipfile

from .xlsx import grid as _grid, sheet_targets as _sheet_targets, \
    shared_strings as _shared_strings


class ValidationError(Exception):
    pass


USER_AGENT = "ObservatoryIngest/0.1 (data pipeline; contact: repo owner)"

PAGE = "https://www.mlit.go.jp/kankocho/tokei_hakusyo/shukuhakutokei.html"
SITE_ROOT = "https://www.mlit.go.jp"

# fetch() rewrites this to the page it resolved from; the individual workbook
# URLs are recorded in the zip's manifest member instead, because a release is
# built from many files and `source_artifacts.url` holds only one.
DOWNLOAD_URL = PAGE

RAW_SUFFIX = ".zip"

# Annual definitive workbooks are fetched from this year forward. 2019 is the
# last full pre-COVID year and the baseline every recovery comparison uses;
# earlier years exist on the page and can be added by moving this back, at
# ~2.6MB of archive per extra year.
FIRST_DETAIL_YEAR = 2019

# The trend workbook's own history start, asserted as a gate.
FIRST_TREND_PERIOD = datetime.date(2011, 1, 1)

# The stratification change: employee-count bands before, room-count bands
# from here, and 21 nationality categories before, 24 from here.
BREAK_PERIOD = datetime.date(2026, 1, 1)


# --- geography ---------------------------------------------------------------

PREFECTURES = [
    ("01", "北海道", "Hokkaido"), ("02", "青森県", "Aomori"),
    ("03", "岩手県", "Iwate"), ("04", "宮城県", "Miyagi"),
    ("05", "秋田県", "Akita"), ("06", "山形県", "Yamagata"),
    ("07", "福島県", "Fukushima"), ("08", "茨城県", "Ibaraki"),
    ("09", "栃木県", "Tochigi"), ("10", "群馬県", "Gunma"),
    ("11", "埼玉県", "Saitama"), ("12", "千葉県", "Chiba"),
    ("13", "東京都", "Tokyo"), ("14", "神奈川県", "Kanagawa"),
    ("15", "新潟県", "Niigata"), ("16", "富山県", "Toyama"),
    ("17", "石川県", "Ishikawa"), ("18", "福井県", "Fukui"),
    ("19", "山梨県", "Yamanashi"), ("20", "長野県", "Nagano"),
    ("21", "岐阜県", "Gifu"), ("22", "静岡県", "Shizuoka"),
    ("23", "愛知県", "Aichi"), ("24", "三重県", "Mie"),
    ("25", "滋賀県", "Shiga"), ("26", "京都府", "Kyoto"),
    ("27", "大阪府", "Osaka"), ("28", "兵庫県", "Hyogo"),
    ("29", "奈良県", "Nara"), ("30", "和歌山県", "Wakayama"),
    ("31", "鳥取県", "Tottori"), ("32", "島根県", "Shimane"),
    ("33", "岡山県", "Okayama"), ("34", "広島県", "Hiroshima"),
    ("35", "山口県", "Yamaguchi"), ("36", "徳島県", "Tokushima"),
    ("37", "香川県", "Kagawa"), ("38", "愛媛県", "Ehime"),
    ("39", "高知県", "Kochi"), ("40", "福岡県", "Fukuoka"),
    ("41", "佐賀県", "Saga"), ("42", "長崎県", "Nagasaki"),
    ("43", "熊本県", "Kumamoto"), ("44", "大分県", "Oita"),
    ("45", "宮崎県", "Miyazaki"), ("46", "鹿児島県", "Kagoshima"),
    ("47", "沖縄県", "Okinawa"),
]

# The Agency's own regional aggregation, republished (再掲) beneath the
# prefectures. Nagano is counted in Hokuriku-Shinetsu and Fukui in Chubu, which
# is why these are not simply sums of the prefectures a reader would guess.
BUREAUS = [
    ("b01", "北海道運輸局", "Hokkaido"),
    ("b02", "東北運輸局", "Tohoku"),
    ("b03", "関東運輸局", "Kanto"),
    ("b04", "北陸信越運輸局", "Hokuriku-Shinetsu"),
    ("b05", "中部運輸局", "Chubu"),
    ("b06", "近畿運輸局", "Kinki"),
    ("b07", "中国運輸局", "Chugoku"),
    ("b08", "四国運輸局", "Shikoku"),
    ("b09", "九州運輸局", "Kyushu"),
    ("b10", "沖縄総合事務局", "Okinawa"),
]

NATIONAL = "jp"

AREA_NAMES = {NATIONAL: ("All Japan", "全国")}
for _code, _ja, _en in PREFECTURES:
    AREA_NAMES[_code] = (_en, _ja)
for _code, _ja, _en in BUREAUS:
    AREA_NAMES[_code] = ("%s region" % _en, _ja)

AREA_ORDER = [NATIONAL] + [c for c, _j, _e in PREFECTURES] + \
             [c for c, _j, _e in BUREAUS]
AREA_INDEX = dict((code, i) for i, code in enumerate(AREA_ORDER))

_PREF_BY_JA = dict((ja, code) for code, ja, _en in PREFECTURES)
_BUREAU_BY_JA = dict((ja, code) for code, ja, _en in BUREAUS)


# --- categories --------------------------------------------------------------

FACILITY_TYPES = [
    ("ryokan", "旅館", "Ryokan"),
    ("resort", "リゾートホテル", "Resort hotel"),
    ("business", "ビジネスホテル", "Business hotel"),
    ("city", "シティホテル", "City hotel"),
    ("minshuku", "簡易宿所", "Simple lodging"),
    ("company", "会社・団体の宿泊所", "Company or association lodging"),
]
_TYPE_BY_JA = dict((ja, code) for code, ja, _en in FACILITY_TYPES)
_TYPE_ORDER = dict((code, i) for i, (code, _j, _e) in enumerate(FACILITY_TYPES))

# Room-count bands, published from January 2026 only. The pre-2026 file bands
# properties by employee count instead; those are a different measurement and
# are deliberately not carried — see the module docstring.
ROOM_BANDS = [
    ("r1-19", "1～19室", "1-19 rooms"),
    ("r20-39", "20～39室", "20-39 rooms"),
    ("r40-99", "40～99室", "40-99 rooms"),
    ("r100-199", "100～199室", "100-199 rooms"),
    ("r200+", "200室以上", "200+ rooms"),
]
_BAND_BY_JA = dict((ja, code) for code, ja, _en in ROOM_BANDS)
_BAND_ORDER = dict((code, i) for i, (code, _j, _e) in enumerate(ROOM_BANDS))

# The survey classifies a *property*, not a guest: "leisure" means a property
# where at least half of guests stayed for leisure. It is a proxy for the
# business/leisure mix, not a measurement of it, and the label says so.
PURPOSES = [
    ("leisure", "観光目的の宿泊者が50％以上", "Leisure-majority properties"),
    ("business", "観光目的の宿泊者が50％未満", "Business-majority properties"),
]
RESIDENCE = [
    ("within", "県内", "Guests resident in the same prefecture"),
    ("outside", "県外", "Guests resident in another prefecture"),
]

# Nationality of the foreign guest. 21 categories to December 2025, 24 from
# January 2026: Nordic region, Middle East and Mexico were split out of the
# residual. `era` records where each one is valid, and the residual is two
# distinct codes because it means different things on either side.
NATIONALITIES = [
    ("kr", "韓国", "South Korea", "both"),
    ("cn", "中国", "China", "both"),
    ("hk", "香港", "Hong Kong", "both"),
    ("tw", "台湾", "Taiwan", "both"),
    ("us", "米国", "U.S.A.", "both"),
    ("ca", "カナダ", "Canada", "both"),
    ("gb", "英国", "United Kingdom", "both"),
    ("de", "ドイツ", "Germany", "both"),
    ("fr", "フランス", "France", "both"),
    ("ru", "ロシア", "Russia", "both"),
    ("sg", "シンガポール", "Singapore", "both"),
    ("th", "タイ", "Thailand", "both"),
    ("my", "マレーシア", "Malaysia", "both"),
    ("in", "インド", "India", "both"),
    ("au", "オーストラリア", "Australia", "both"),
    ("id", "インドネシア", "Indonesia", "both"),
    ("vn", "ベトナム", "Vietnam", "both"),
    ("ph", "フィリピン", "Philippines", "both"),
    ("it", "イタリア", "Italy", "both"),
    ("es", "スペイン", "Spain", "both"),
    ("nordic", "北欧地域", "Nordic region", "new"),
    ("mideast", "中東地域", "Middle East", "new"),
    ("mx", "メキシコ", "Mexico", "new"),
    ("other", "その他", "Other (2026 basis)", "new"),
    ("other-pre2026", "その他", "Other (pre-2026 basis)", "old"),
]
_NAT_ORDER = dict((code, i) for i, (code, _j, _e, _era)
                  in enumerate(NATIONALITIES))
_NAT_OLD = dict((ja, code) for code, ja, _en, era in NATIONALITIES
                if era in ("both", "old"))
_NAT_NEW = dict((ja, code) for code, ja, _en, era in NATIONALITIES
                if era in ("both", "new"))


# Municipalities the survey names individually. The list is a *committed*
# registry, not whatever the file happens to contain: a municipality appearing
# unannounced fails the ingest rather than being silently added, because a new
# code is a decision. The Agency prints a municipality only in months where at
# least ten of its properties responded, so rows come and go; that is handled
# as missing data, not as a new series.
#
# City names are carried in Japanese. The prefecture is romanised, which is
# what a reader needs to navigate; per-municipality romanisation would have to
# come from a published kana table rather than be invented here.
MUNICIPALITIES = [
    ("01-01", "01", "札幌市"),
    ("01-02", "01", "函館市"),
    ("01-03", "01", "小樽市"),
    ("01-04", "01", "旭川市"),
    ("01-05", "01", "釧路市"),
    ("01-06", "01", "帯広市"),
    ("01-07", "01", "北見市"),
    ("01-08", "01", "苫小牧市"),
    ("01-09", "01", "千歳市"),
    ("01-10", "01", "網走市"),
    ("01-11", "01", "富良野市"),
    ("01-12", "01", "登別市"),
    ("01-13", "01", "虻田郡倶知安町"),
    ("01-14", "01", "後志総合振興局倶知安町"),
    ("02-01", "02", "青森市"),
    ("02-02", "02", "弘前市"),
    ("02-03", "02", "八戸市"),
    ("03-01", "03", "盛岡市"),
    ("03-02", "03", "花巻市"),
    ("03-03", "03", "北上市"),
    ("03-04", "03", "一関市"),
    ("03-05", "03", "八幡平市"),
    ("04-01", "04", "仙台市"),
    ("04-02", "04", "大崎市"),
    ("05-01", "05", "秋田市"),
    ("05-02", "05", "大館市"),
    ("05-03", "05", "仙北市"),
    ("06-01", "06", "山形市"),
    ("06-02", "06", "米沢市"),
    ("06-03", "06", "鶴岡市"),
    ("06-04", "06", "酒田市"),
    ("06-05", "06", "天童市"),
    ("07-01", "07", "福島市"),
    ("07-02", "07", "会津若松市"),
    ("07-03", "07", "郡山市"),
    ("07-04", "07", "いわき市"),
    ("07-05", "07", "南相馬市"),
    ("07-06", "07", "耶麻郡猪苗代町"),
    ("08-01", "08", "水戸市"),
    ("08-02", "08", "つくば市"),
    ("08-03", "08", "土浦市"),
    ("08-04", "08", "神栖市"),
    ("09-01", "09", "宇都宮市"),
    ("09-02", "09", "日光市"),
    ("09-03", "09", "那須塩原市"),
    ("09-04", "09", "小山市"),
    ("09-05", "09", "那須郡那須町"),
    ("10-01", "10", "前橋市"),
    ("10-02", "10", "高崎市"),
    ("10-03", "10", "渋川市"),
    ("10-04", "10", "吾妻郡嬬恋村"),
    ("10-05", "10", "吾妻郡草津町"),
    ("10-06", "10", "利根郡みなかみ町"),
    ("11-01", "11", "さいたま市"),
    ("11-02", "11", "熊谷市"),
    ("12-01", "12", "千葉市"),
    ("12-02", "12", "木更津市"),
    ("12-03", "12", "成田市"),
    ("12-04", "12", "市原市"),
    ("12-05", "12", "鴨川市"),
    ("12-06", "12", "浦安市"),
    ("12-07", "12", "南房総市"),
    ("13-01", "13", "千代田区"),
    ("13-02", "13", "中央区"),
    ("13-03", "13", "港区"),
    ("13-04", "13", "新宿区"),
    ("13-05", "13", "台東区"),
    ("13-06", "13", "墨田区"),
    ("13-07", "13", "江東区"),
    ("13-08", "13", "品川区"),
    ("13-09", "13", "大田区"),
    ("13-10", "13", "渋谷区"),
    ("13-11", "13", "豊島区"),
    ("13-12", "13", "北区"),
    ("13-13", "13", "荒川区"),
    ("13-14", "13", "八王子市"),
    ("14-01", "14", "横浜市"),
    ("14-02", "14", "川崎市"),
    ("14-03", "14", "相模原市"),
    ("14-04", "14", "鎌倉市"),
    ("14-05", "14", "藤沢市"),
    ("14-06", "14", "足柄下郡箱根町"),
    ("14-07", "14", "小田原市"),
    ("15-01", "15", "新潟市"),
    ("15-02", "15", "長岡市"),
    ("15-03", "15", "妙高市"),
    ("15-04", "15", "上越市"),
    ("15-05", "15", "佐渡市"),
    ("15-06", "15", "南魚沼市"),
    ("15-07", "15", "南魚沼郡湯沢町"),
    ("16-01", "16", "富山市"),
    ("17-01", "17", "金沢市"),
    ("17-02", "17", "加賀市"),
    ("17-03", "17", "小松市"),
    ("18-01", "18", "福井市"),
    ("18-02", "18", "敦賀市"),
    ("18-03", "18", "あわら市"),
    ("19-01", "19", "甲府市"),
    ("19-02", "19", "富士吉田市"),
    ("19-03", "19", "北杜市"),
    ("19-04", "19", "笛吹市"),
    ("19-05", "19", "南都留郡山中湖村"),
    ("19-06", "19", "南都留郡富士河口湖町"),
    ("20-01", "20", "長野市"),
    ("20-02", "20", "松本市"),
    ("20-03", "20", "上田市"),
    ("20-04", "20", "諏訪市"),
    ("20-05", "20", "佐久市"),
    ("20-06", "20", "飯田市"),
    ("20-07", "20", "茅野市"),
    ("20-08", "20", "北佐久郡軽井沢町"),
    ("20-09", "20", "大町市"),
    ("20-10", "20", "北安曇郡白馬村"),
    ("20-11", "20", "下高井郡山ノ内町"),
    ("20-12", "20", "安曇野市"),
    ("20-13", "20", "下高井郡野沢温泉村"),
    ("21-01", "21", "岐阜市"),
    ("21-02", "21", "高山市"),
    ("21-03", "21", "下呂市"),
    ("21-04", "21", "郡上市"),
    ("22-01", "22", "静岡市"),
    ("22-02", "22", "浜松市"),
    ("22-03", "22", "沼津市"),
    ("22-04", "22", "熱海市"),
    ("22-05", "22", "富士宮市"),
    ("22-06", "22", "伊東市"),
    ("22-07", "22", "富士市"),
    ("22-08", "22", "掛川市"),
    ("22-09", "22", "御殿場市"),
    ("22-10", "22", "伊豆市"),
    ("22-11", "22", "下田市"),
    ("22-12", "22", "伊豆の国市"),
    ("22-13", "22", "賀茂郡東伊豆町"),
    ("23-01", "23", "名古屋市"),
    ("23-02", "23", "豊橋市"),
    ("23-03", "23", "豊田市"),
    ("23-04", "23", "蒲郡市"),
    ("23-05", "23", "常滑市"),
    ("24-01", "24", "津市"),
    ("24-02", "24", "伊勢市"),
    ("24-03", "24", "鈴鹿市"),
    ("24-04", "24", "鳥羽市"),
    ("24-05", "24", "志摩市"),
    ("24-06", "24", "四日市市"),
    ("25-01", "25", "大津市"),
    ("25-02", "25", "彦根市"),
    ("25-03", "25", "高島市"),
    ("26-01", "26", "京都市"),
    ("26-02", "26", "京丹後市"),
    ("27-01", "27", "大阪市"),
    ("27-02", "27", "堺市"),
    ("27-03", "27", "泉佐野市"),
    ("28-01", "28", "神戸市"),
    ("28-02", "28", "姫路市"),
    ("28-03", "28", "豊岡市"),
    ("28-04", "28", "洲本市"),
    ("29-01", "29", "奈良市"),
    ("30-01", "30", "和歌山市"),
    ("30-02", "30", "伊都郡高野町"),
    ("30-03", "30", "西牟婁郡白浜町"),
    ("30-04", "30", "田辺市"),
    ("31-01", "31", "鳥取市"),
    ("31-02", "31", "米子市"),
    ("32-01", "32", "松江市"),
    ("32-02", "32", "出雲市"),
    ("33-01", "33", "岡山市"),
    ("33-02", "33", "倉敷市"),
    ("34-01", "34", "広島市"),
    ("34-02", "34", "呉市"),
    ("34-03", "34", "福山市"),
    ("34-04", "34", "廿日市市"),
    ("35-01", "35", "下関市"),
    ("35-02", "35", "山口市"),
    ("35-03", "35", "周南市"),
    ("36-01", "36", "徳島市"),
    ("36-02", "36", "鳴門市"),
    ("36-03", "36", "三好市"),
    ("37-01", "37", "高松市"),
    ("38-01", "38", "松山市"),
    ("38-02", "38", "今治市"),
    ("39-01", "39", "高知市"),
    ("40-01", "40", "北九州市"),
    ("40-02", "40", "福岡市"),
    ("41-01", "41", "佐賀市"),
    ("41-02", "41", "嬉野市"),
    ("41-03", "41", "唐津市"),
    ("42-01", "42", "長崎市"),
    ("42-02", "42", "佐世保市"),
    ("42-03", "42", "諫早市"),
    ("42-04", "42", "五島市"),
    ("43-01", "43", "熊本市"),
    ("43-02", "43", "天草市"),
    ("44-01", "44", "大分市"),
    ("44-02", "44", "別府市"),
    ("44-03", "44", "日田市"),
    ("45-01", "45", "宮崎市"),
    ("45-02", "45", "西臼杵郡高千穂町"),
    ("46-01", "46", "鹿児島市"),
    ("46-02", "46", "薩摩川内市"),
    ("46-03", "46", "霧島市"),
    ("46-04", "46", "奄美市"),
    ("46-05", "46", "熊毛郡南種子町"),
    ("46-06", "46", "指宿市"),
    ("47-01", "47", "那覇市"),
    ("47-02", "47", "石垣市"),
    ("47-03", "47", "宮古島市"),
    ("47-04", "47", "国頭郡本部町"),
    ("47-05", "47", "名護市"),
    ("47-06", "47", "国頭郡恩納村"),
    ("47-07", "47", "国頭郡今帰仁村"),
]
_MUNI_BY_KEY = dict(((pref, city), code)
                    for code, pref, city in MUNICIPALITIES)
_MUNI_ORDER = dict((code, i) for i, (code, _p, _c) in enumerate(MUNICIPALITIES))

# The Agency spells a prefecture prefix inconsistently — 和歌山県和歌山市 in
# one release and 和歌山和歌山市 in another — so both the full name and the
# stem are accepted, longest first, and the municipality is identified by
# (prefecture, city) rather than by the printed string.
_MUNI_PREFIXES = sorted(
    [(ja, code) for code, ja, _en in PREFECTURES] +
    [(re.sub(r"[都道府県]$", "", ja), code) for code, ja, _en in PREFECTURES
     if re.sub(r"[都道府県]$", "", ja) != ja],
    key=lambda pair: -len(pair[0]))


def _municipality_of(label):
    """A printed municipality row -> our stable code, or None if unknown."""
    for prefix, pref in _MUNI_PREFIXES:
        if label.startswith(prefix):
            return _MUNI_BY_KEY.get((pref, label[len(prefix):]))
    return None


DATASET = {
    "slug": "accommodation-jp",
    "title": "Accommodation Survey — guest nights and occupancy",
    "country": "Japan",
    "agency": "Japan Tourism Agency",
    "agency_ja": "観光庁",
    "base": None,
    "frequency": "monthly",
    "description": (
        "Monthly guest nights and room occupancy in Japanese accommodation, "
        "from the Japan Tourism Agency's Accommodation Survey. Guest nights "
        "for the nation, the 47 prefectures and the 10 transport-bureau "
        "regions run from January 2011, split into Japanese and foreign "
        "guests, with room occupancy by hotel type over the same span. From "
        "January 2019 the detail opens up: foreign guest nights by 24 visitor "
        "nationalities, guest nights by hotel type, and the leisure/business "
        "and in-prefecture/out-of-prefecture splits. Facility-size bands and "
        "175 named municipalities begin in January 2026, when the survey "
        "changed how it stratifies properties."
    ),
}

SOURCE = {
    "source_id": "jta:shukuhaku-ryoko-tokei",
    "name": "JTA — Accommodation Survey (trend, annual definitive and monthly)",
    "name_ja": "観光庁 宿泊旅行統計調査",
    "url": PAGE,
    "license_note": (
        "Japan Tourism Agency statistics may be reproduced with attribution "
        "under the Government of Japan Standard Terms of Use. Credit as "
        "「観光庁『宿泊旅行統計調査』」 / Japan Tourism Agency, Accommodation "
        "Survey. Figures are estimates grossed up from a sample survey and "
        "carry published standard errors."
    ),
}


# --- fetch -------------------------------------------------------------------

def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


_LINK = re.compile(r'href="([^"]+\.xlsx)"[^>]*>(.*?)</a>', re.S)
_TREND = re.compile(r"推移表")
_MONTHLY = re.compile(r"(\d{4})年.*?(\d{1,2})月分.*?第2次速報値")
_ANNUAL = re.compile(r"(\d{4})年.*?年の確定値.*?集計結果")


def resolve_downloads():
    """Every workbook this release is built from, discovered from the page.

    Each link is a rotating numeric content id, so nothing here may be
    hard-coded. Returns {member name: absolute url} with names that sort into
    a stable order, which is what makes the archived zip reproducible.

    Missing any of the three kinds means the page has been restructured and
    the ingest must stop rather than publish a partial picture.
    """
    html = _get(PAGE).decode("utf-8", "replace")
    trend, monthly, annual = [], {}, {}
    for href, label_html in _LINK.findall(html):
        label = re.sub(r"<[^>]+>", " ", label_html)
        label = re.sub(r"\s+", " ", label).strip()
        url = href if href.startswith("http") else SITE_ROOT + href
        if _TREND.search(label):
            trend.append(url)
            continue
        m = _MONTHLY.search(label)
        if m:
            monthly[(int(m.group(1)), int(m.group(2)))] = url
            continue
        m = _ANNUAL.search(label)
        if m and int(m.group(1)) >= FIRST_DETAIL_YEAR:
            annual[int(m.group(1))] = url

    if len(set(trend)) != 1:
        raise ValidationError(
            "expected exactly one 推移表 workbook on %s, found %d"
            % (PAGE, len(set(trend))))
    if not annual:
        raise ValidationError(
            "no annual definitive workbook from %d onward found on %s"
            % (FIRST_DETAIL_YEAR, PAGE))
    if not monthly:
        raise ValidationError("no monthly second-preliminary workbook on %s" % PAGE)

    out = {"trend.xlsx": trend[0]}
    for year in sorted(annual):
        out["annual-%04d.xlsx" % year] = annual[year]
    for year, month in sorted(monthly):
        out["monthly-%04d-%02d.xlsx" % (year, month)] = monthly[(year, month)]
    return out


def fetch():
    """All of the workbooks, bundled into one deterministic zip.

    The runner archives a single artifact per release and hashes it to decide
    whether anything changed, so the bundle must be byte-identical when the
    inputs are. Every member therefore gets a fixed timestamp, members are
    written in sorted order, and nothing is compressed — the xlsx files are
    already deflate archives, so storing them keeps the bundle reproducible
    and costs nothing.

    A `manifest.txt` member records which URL each workbook came from, since
    `source_artifacts.url` can hold only the page they were resolved from.
    """
    urls = resolve_downloads()
    files = dict((name, _get(url)) for name, url in sorted(urls.items()))
    manifest = "".join("%s\t%s\n" % (name, urls[name]) for name in sorted(urls))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name in sorted(files) + ["manifest.txt"]:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            payload = (manifest.encode("utf-8") if name == "manifest.txt"
                       else files[name])
            z.writestr(info, payload)
    return buf.getvalue()


# --- reading the workbooks ---------------------------------------------------

def _colnum(letter):
    n = 0
    for ch in letter:
        n = n * 26 + (ord(ch) - 64)
    return n


def _text(cell):
    return (cell[0] if cell else "") or ""


def _clean(text):
    """Header and label text with the layout noise taken out.

    Cells wrap, are padded with ideographic spaces, and carry footnote marks
    such as "1)" or "2)" glued onto the label. Matching happens against the
    squeezed form so a rewrapped header never changes what a column means.
    """
    text = (text or "").replace("　", " ")
    text = re.sub(r"\s+", "", text)
    return text


def _label(text):
    return re.sub(r"\s+", " ", (text or "").replace("　", " ")).strip()


# Cells the Agency prints where a value does not exist: no responding
# properties, or a figure suppressed as too thin to publish. All of them mean
# missing, and missing is never zero.
_MISSING = ("-", "‐", "‒", "–", "—", "－", "…", "...",
            "X", "x", "Ｘ", "***", "**", "*")


def _num(text, where):
    """(value, flagged) for a data cell, or (None, False) when it is missing.

    A leading asterisk is the Agency's own reliability mark on an otherwise
    real figure. The value is kept — dropping data the publisher chose to
    publish would be our judgement replacing theirs — and the flag is counted
    on the release so a reader can see how much of a view rests on marked
    cells.
    """
    raw = _label(text)
    if not raw or raw in _MISSING:
        return None, False
    flagged = raw.startswith("*")
    stripped = raw.lstrip("*").replace(",", "").replace("，", "")
    if not stripped or stripped in _MISSING:
        return None, False
    try:
        return float(stripped), flagged
    except ValueError:
        raise ValidationError("%s: non-numeric value %r" % (where, raw))


_ERA = re.compile(r"^(令和|平成)\s*(元|\d+)\s*年")


def _era_year(text):
    """'令和8年6月' -> 2026. None when the text is not an era-stamped period."""
    m = _ERA.match(_label(text))
    if not m:
        return None
    n = 1 if m.group(2) == "元" else int(m.group(2))
    return (2018 if m.group(1) == "令和" else 1988) + n


_FOOTNOTE = re.compile(r"^(\d+[)）]|※|注|＊)")


def _area_of(label, where):
    """A row label -> our area code, or None for a row that is not an area.

    Anything that looks like data but is not recognised raises: a renamed
    prefecture or a new aggregate must be a deliberate change, not a silently
    dropped row.
    """
    text = _label(label)
    if not text:
        return None
    if _FOOTNOTE.match(text) or text.startswith("運輸局等"):
        return None
    if _era_year(text) is not None:          # the national row of a detail table
        return NATIONAL
    if _clean(text) in ("全国",):            # the national row of a trend sheet
        return NATIONAL
    if text in _BUREAU_BY_JA:
        return _BUREAU_BY_JA[text]
    m = re.match(r"^(\d{2})\s*(.+)$", text)
    if m:
        code, name = m.group(1), _clean(m.group(2))
        if _PREF_BY_JA.get(name) != code:
            raise ValidationError(
                "%s: row %r does not match the prefecture registry" % (where, text))
        return code
    if len(text) > 30:                       # a title or explanatory line
        return None
    raise ValidationError("%s: unrecognised row label %r" % (where, text))


# Footnote references are glued onto header labels — "県内 1)", "延べ宿泊者数
# 1)、2)" — and which notes a table carries changes between releases. They are
# stripped before a label is matched, so a new footnote never silently
# redefines a column.
_NOTE = re.compile(r"\d+[)）]")


def _key(text):
    return _NOTE.sub("", _clean(text)).strip("、,")


def _header(sheet, rownum):
    """{column letter: label} for one header row, footnote marks removed."""
    return dict((col, _key(_text(cell)))
                for col, cell in sheet.get(rownum, {}).items()
                if _key(_text(cell)))


def _find(header, predicate, where, what):
    hits = [col for col, text in header.items() if predicate(text)]
    if len(hits) != 1:
        raise ValidationError(
            "%s: expected exactly one %s column, found %d" % (where, what, len(hits)))
    return hits[0]


_TYPE_BY_CLEAN = dict((_clean(ja), code) for code, ja, _en in FACILITY_TYPES)
_BAND_BY_CLEAN = dict((_clean(ja), code) for code, ja, _en in ROOM_BANDS)
_NAT_OLD_CLEAN = dict((_clean(ja), code) for ja, code in _NAT_OLD.items())
_NAT_NEW_CLEAN = dict((_clean(ja), code) for ja, code in _NAT_NEW.items())

# The Agency renamed two columns partway through without changing what they
# count: アメリカ became 米国 and イギリス became 英国 with the 2022 workbook.
# They are the same series and are read as one.
_NAT_ALIASES = {"アメリカ": "米国", "イギリス": "英国"}
_LEISURE, _BUSINESS = _clean(PURPOSES[0][1]), _clean(PURPOSES[1][1])
_WITHIN, _OUTSIDE = _clean(RESIDENCE[0][1]), _clean(RESIDENCE[1][1])


# --- the trend workbook: history for the backbone series ---------------------

def _trend_periods(sheet, where):
    """column letter -> month, from the era row (3) above the month row (4).

    A year header governs every month column from itself up to the next one,
    which is what makes 2019 work: the file splits it into 平成31年 (January to
    April) and 令和元年 (May to December), and both resolve to 2019 without a
    special case.
    """
    year_at = {}
    for col, text in _header(sheet, 3).items():
        year = _era_year(text)
        if year is not None:
            year_at[_colnum(col)] = year
    months = {}
    for col, text in _header(sheet, 4).items():
        m = re.match(r"^(\d{1,2})月$", text)
        if m:
            months[col] = int(m.group(1))
    if not year_at or not months:
        raise ValidationError("%s: no year/month header found" % where)
    starts = sorted(year_at)
    out = {}
    for col, month in months.items():
        prior = [s for s in starts if s <= _colnum(col)]
        if not prior:
            raise ValidationError("%s: month column %s has no year" % (where, col))
        out[col] = datetime.date(year_at[prior[-1]], month, 1)
    return out


def _read_trend_area(sheet, template, where):
    """A trend sheet whose only dimension is the area in column A."""
    periods = _trend_periods(sheet, where)
    rows = []
    for rownum in sorted(sheet):
        if rownum <= 4:
            continue
        area = _area_of(_text(sheet[rownum].get("A")), where)
        if area is None:
            continue
        for col, period in periods.items():
            value, flagged = _num(_text(sheet[rownum].get(col)),
                                  "%s row %d" % (where, rownum))
            if value is not None:
                rows.append((template % area, period, value, flagged))
    return rows


def _read_trend_occupancy(sheet, where):
    """The occupancy trend sheet: area in A, "計" then the six types in B."""
    periods = _trend_periods(sheet, where)
    rows, area = [], None
    for rownum in sorted(sheet):
        if rownum <= 4:
            continue
        row = sheet[rownum]
        if _label(_text(row.get("A"))):
            found = _area_of(_text(row.get("A")), where)
            if found is not None:
                area = found
        if area is None:
            continue
        kind = _clean(_text(row.get("B")))
        if kind == "計":
            code = "occ.%s" % area
        elif kind in _TYPE_BY_CLEAN:
            code = "occ.%s.type.%s" % (area, _TYPE_BY_CLEAN[kind])
        else:
            continue
        for col, period in periods.items():
            value, flagged = _num(_text(row.get(col)),
                                  "%s row %d" % (where, rownum))
            if value is not None:
                rows.append((code, period, value, flagged))
    return rows


TREND_SHEETS = [
    ("1-1", "nights.%s"), ("旧1-2", "nights.%s"),
    ("2-1", "nights.%s.jp"), ("旧2-2", "nights.%s.jp"),
    ("3-1", "nights.%s.fx"), ("旧3-2", "nights.%s.fx"),
]
TREND_OCCUPANCY = ("4-1", "旧4-2")


def _parse_trend(sheets):
    rows = []
    for name, template in TREND_SHEETS:
        if name in sheets:
            rows.extend(_read_trend_area(sheets[name], template, "trend %s" % name))
    for name in TREND_OCCUPANCY:
        if name in sheets:
            rows.extend(_read_trend_occupancy(sheets[name], "trend %s" % name))
    if not rows:
        raise ValidationError(
            "the trend workbook yielded nothing — expected sheets %s"
            % ([n for n, _t in TREND_SHEETS] + list(TREND_OCCUPANCY),))
    return rows


# --- the detail workbooks: one sheet per table per month ---------------------

def _data_rows(sheet, first_row, where):
    """(row number, area code) for every area row of a detail table."""
    for rownum in sorted(sheet):
        if rownum < first_row:
            continue
        area = _area_of(_text(sheet[rownum].get("A")), where)
        if area is not None:
            yield rownum, area


def _read_by_type(sheet, period, where):
    """第4表 — guest nights and foreign guest nights by hotel type."""
    h4, h5 = _header(sheet, 4), _header(sheet, 5)
    total_col = _find(h4, lambda t: "延べ宿泊者数" in t and "外国人" not in t,
                      where, "guest nights")
    fx_col = _find(h4, lambda t: "外国人延べ宿泊者数" in t, where,
                   "foreign guest nights")
    left, right = _colnum(total_col), _colnum(fx_col)
    types_total, types_fx = {}, {}
    for col, text in h5.items():
        code = _TYPE_BY_CLEAN.get(text)
        if code is None:
            continue
        if left < _colnum(col) < right:
            types_total[col] = code
        elif _colnum(col) > right:
            types_fx[col] = code
    for group, label in ((types_total, "guest nights"), (types_fx, "foreign")):
        if len(group) != len(FACILITY_TYPES):
            raise ValidationError(
                "%s: found %d of %d %s hotel-type columns"
                % (where, len(group), len(FACILITY_TYPES), label))

    rows = []
    for rownum, area in _data_rows(sheet, 6, where):
        row = sheet[rownum]
        cells = [(total_col, "nights.%s" % area), (fx_col, "nights.%s.fx" % area)]
        cells += [(c, "nights.%s.type.%s" % (area, t)) for c, t in types_total.items()]
        cells += [(c, "nightsfx.%s.type.%s" % (area, t)) for c, t in types_fx.items()]
        for col, code in cells:
            value, flagged = _num(_text(row.get(col)), "%s row %d" % (where, rownum))
            if value is not None:
                rows.append((code, period, value, flagged))
    return rows


def _read_by_nationality(sheet, period, era, where):
    """参考第1表 — foreign guest nights by the visitor's nationality.

    A narrower universe than the headline: larger properties only (20+ rooms
    from 2026, 10+ employees before). Column B is that universe's own total,
    carried as `.nat.all` so a share or a contribution computed on this table
    reconciles against the right denominator rather than against the
    all-properties foreign guest nights, which it would not match.
    """
    h4, h5 = _header(sheet, 4), _header(sheet, 5)
    base_col = _find(h4, lambda t: "外国人延べ宿泊者数" in t, where,
                     "foreign guest nights")
    lookup = _NAT_NEW_CLEAN if era == "new" else _NAT_OLD_CLEAN
    expected = len(_NAT_NEW_CLEAN) if era == "new" else len(_NAT_OLD_CLEAN)
    nat_cols = {}
    for col, text in h5.items():
        if _colnum(col) <= _colnum(base_col):
            continue
        code = lookup.get(_NAT_ALIASES.get(text, text))
        if code is None:
            raise ValidationError(
                "%s: unknown nationality column %r — the source has changed "
                "its category list and the registry must be updated "
                "deliberately" % (where, text))
        nat_cols[col] = code
    if len(nat_cols) != expected:
        raise ValidationError(
            "%s: found %d nationality columns, expected %d"
            % (where, len(nat_cols), expected))

    rows = []
    for rownum, area in _data_rows(sheet, 6, where):
        row = sheet[rownum]
        cells = [(base_col, "nightsfx.%s.nat.all" % area)]
        cells += [(c, "nightsfx.%s.nat.%s" % (area, n)) for c, n in nat_cols.items()]
        for col, code in cells:
            value, flagged = _num(_text(row.get(col)), "%s row %d" % (where, rownum))
            if value is not None:
                rows.append((code, period, value, flagged))
    return rows


def _read_purpose_residence(sheet, period, where):
    """第9表 — guest nights by property purpose mix and by guest residence."""
    h5, h6 = _header(sheet, 5), _header(sheet, 6)
    leisure_col = _find(h5, lambda t: t == _LEISURE, where, "leisure-majority")
    business_col = _find(h5, lambda t: t == _BUSINESS, where, "business-majority")
    res_cols = {}
    for col, text in h6.items():
        if _colnum(col) >= _colnum(leisure_col):
            continue
        if text == _WITHIN:
            res_cols[col] = "within"
        elif text == _OUTSIDE:
            res_cols[col] = "outside"
    if len(res_cols) != 2:
        raise ValidationError(
            "%s: found %d residence columns, expected 2" % (where, len(res_cols)))

    rows = []
    for rownum, area in _data_rows(sheet, 6, where):
        row = sheet[rownum]
        cells = [(leisure_col, "nights.%s.purpose.leisure" % area),
                 (business_col, "nights.%s.purpose.business" % area)]
        cells += [(c, "nights.%s.res.%s" % (area, r)) for c, r in res_cols.items()]
        for col, code in cells:
            value, flagged = _num(_text(row.get(col)), "%s row %d" % (where, rownum))
            if value is not None:
                rows.append((code, period, value, flagged))
    return rows


def _read_room_bands(sheet, period, where):
    """第2表 — guest nights by the property's room count. 2026 onward only."""
    h5 = _header(sheet, 5)
    band_cols = dict((col, _BAND_BY_CLEAN[text]) for col, text in h5.items()
                     if text in _BAND_BY_CLEAN)
    if len(band_cols) != len(ROOM_BANDS):
        raise ValidationError(
            "%s: found %d of %d room-count band columns — this table is only "
            "read for periods from %s, when the survey switched to room-count "
            "stratification" % (where, len(band_cols), len(ROOM_BANDS),
                                BREAK_PERIOD))
    rows = []
    for rownum, area in _data_rows(sheet, 6, where):
        row = sheet[rownum]
        for col, band in band_cols.items():
            value, flagged = _num(_text(row.get(col)), "%s row %d" % (where, rownum))
            if value is not None:
                rows.append(("nights.%s.rooms.%s" % (area, band), period,
                             value, flagged))
    return rows


def _read_municipal(sheet, period, metric, where, unknown):
    """参考第6表 / 第8表 / 第12表 — one metric for each named municipality.

    The Agency prints a municipality only in months where at least ten of its
    properties responded, so this list breathes from month to month. A name we
    have no code for is therefore *reported*, not fatal: refusing to publish
    the whole survey because one town crossed a response threshold would trade
    a complete release for a cosmetic one. validate() gates on how many are
    unknown, which is what would actually signal a restructured table.
    """
    rows = []
    for rownum in sorted(sheet):
        if rownum < 7:
            continue
        label = _label(_text(sheet[rownum].get("A")))
        if not label or _FOOTNOTE.match(label) or label.startswith("参考"):
            continue
        if len(label) > 20:
            continue                          # a heading or explanatory line
        code = _municipality_of(label)
        if code is None:
            unknown.add(label)
            continue
        value, flagged = _num(_text(sheet[rownum].get("B")),
                              "%s row %d" % (where, rownum))
        if value is not None:
            rows.append(("muni.%s.%s" % (code, metric), period, value, flagged))
    return rows


# Table number -> (reader, era restriction). The numbering is shared by the
# annual definitive and monthly preliminary workbooks, which is what lets one
# set of readers serve both.
_MUNICIPAL_TABLES = (("参考第6表", "nights"), ("参考第8表", "nightsfx"),
                     ("参考第12表", "occ"))


def _month_sheets(names, table):
    """{month number: sheet name} for one table across a workbook."""
    out = {}
    pattern = re.compile(r"^%s\((\d{1,2})月\)$" % re.escape(table))
    for name in names:
        m = pattern.match(name.strip())
        if m:
            out[int(m.group(1))] = name
    return out


# --- parse -------------------------------------------------------------------

def _workbook(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    return z, _shared_strings(z), _sheet_targets(z)


def _era(period):
    return "new" if period >= BREAK_PERIOD else "old"


def _is_percent(code):
    return code.startswith("occ.") or code.endswith(".occ")


# Where two workbooks carry the same figure, the more settled one wins.
RANK_MONTHLY, RANK_TREND, RANK_ANNUAL = 0, 1, 2


def _parse_detail(raw, months, label, unknown):
    """Every dimensional table of one detail workbook, for the months given."""
    z, shared, targets = _workbook(raw)
    names = list(targets)

    def sheet(name):
        return _grid(z, shared, None, targets[name])

    rows = []
    for table, reader in (("第4表", _read_by_type),
                          ("第9表", _read_purpose_residence)):
        found = _month_sheets(names, table)
        for month, name in sorted(found.items()):
            if month not in months:
                continue
            where = "%s %s" % (label, name)
            rows.extend(reader(sheet(name), months[month], where))

    for month, name in sorted(_month_sheets(names, "参考第1表").items()):
        if month not in months:
            continue
        period = months[month]
        rows.extend(_read_by_nationality(sheet(name), period, _era(period),
                                         "%s %s" % (label, name)))

    for month, name in sorted(_month_sheets(names, "第2表").items()):
        if month not in months or _era(months[month]) != "new":
            continue
        rows.extend(_read_room_bands(sheet(name), months[month],
                                     "%s %s" % (label, name)))

    for table, metric in _MUNICIPAL_TABLES:
        for month, name in sorted(_month_sheets(names, table).items()):
            if month not in months or _era(months[month]) != "new":
                continue
            rows.extend(_read_municipal(sheet(name), months[month], metric,
                                        "%s %s" % (label, name), unknown))
    return rows


_MEMBER = re.compile(r"^(annual|monthly)-(\d{4})(?:-(\d{2}))?\.xlsx$")


def parse(raw_bytes):
    bundle = zipfile.ZipFile(io.BytesIO(raw_bytes))
    members = sorted(bundle.namelist())
    if "trend.xlsx" not in members:
        raise ValidationError("the bundle has no trend workbook")

    values = {}                     # (code, period) -> [value, flagged, rank]
    stats = {"compared": 0, "mismatch": 0, "flagged": 0}
    unknown = set()

    def put(rows, rank):
        for code, period, value, flagged in rows:
            key = (code, period)
            held = values.get(key)
            if held is not None and held[2] != rank:
                # Two independently published workbooks carrying the same
                # figure: a free check that a column has not been misread.
                stats["compared"] += 1
                tolerance = 0.15 if _is_percent(code) else 0.5
                if abs(held[0] - value) > tolerance:
                    stats["mismatch"] += 1
            if held is None or rank >= held[2]:
                values[key] = [value, flagged, rank]

    # Monthly preliminary first, so anything more settled overwrites it.
    for name in members:
        m = _MEMBER.match(name)
        if not m or m.group(1) != "monthly":
            continue
        year, month = int(m.group(2)), int(m.group(3))
        put(_parse_detail(bundle.read(name), {month: datetime.date(year, month, 1)},
                          name, unknown), RANK_MONTHLY)

    z, shared, targets = _workbook(bundle.read("trend.xlsx"))
    sheets = dict((name.strip(), _grid(z, shared, None, target))
                  for name, target in targets.items())
    put(_parse_trend(sheets), RANK_TREND)

    for name in members:
        m = _MEMBER.match(name)
        if not m or m.group(1) != "annual":
            continue
        year = int(m.group(2))
        months = dict((month, datetime.date(year, month, 1))
                      for month in range(1, 13))
        put(_parse_detail(bundle.read(name), months, name, unknown), RANK_ANNUAL)

    observations = []
    for (code, period), (value, flagged, _rank) in values.items():
        obs = {"code": code, "period": period, "value": value}
        if flagged:
            # The Agency's own reliability mark on the cell. Revision status
            # and reliability are not trust levels and never become a badge.
            obs["flagged"] = True
            stats["flagged"] += 1
        observations.append(obs)
    observations.sort(key=lambda o: (o["period"], o["code"]))

    series = []
    for code in sorted(set(o["code"] for o in observations)):
        name_en, name_ja, unit, order = _describe(code)
        series.append({
            "code": code, "name_en": name_en, "name_ja": name_ja,
            "unit": unit,
            "weight_per_10000": None,   # meaningless for nights and for a rate
            "sort_order": order,
        })
    series.sort(key=lambda s: s["sort_order"])
    stats["unregistered_municipalities"] = sorted(unknown)
    parse.stats = stats
    return series, observations


# --- naming ------------------------------------------------------------------

_FAMILY_RANK = {
    "nights": 0, "nights.jp": 1, "nights.fx": 2, "occ": 3, "occ.type": 4,
    "nights.type": 5, "nightsfx.type": 6, "nightsfx.nat": 7, "nights.res": 8,
    "nights.purpose": 9, "nights.rooms": 10, "muni": 11,
}
_TYPE_EN = dict((code, en) for code, _ja, en in FACILITY_TYPES)
_TYPE_JA = dict((code, ja) for code, ja, _en in FACILITY_TYPES)
_BAND_EN = dict((code, en) for code, _ja, en in ROOM_BANDS)
_BAND_JA = dict((code, ja) for code, ja, _en in ROOM_BANDS)
_NAT_EN = dict((code, en) for code, _ja, en, _e in NATIONALITIES)
_NAT_JA = dict((code, ja) for code, ja, _en, _e in NATIONALITIES)
_PURPOSE_EN = dict((code, en) for code, _ja, en in PURPOSES)
_PURPOSE_JA = dict((code, ja) for code, ja, _en in PURPOSES)
_RES_EN = dict((code, en) for code, _ja, en in RESIDENCE)
_RES_JA = dict((code, ja) for code, ja, _en in RESIDENCE)
_MUNI_PREF = dict((code, pref) for code, pref, _city in MUNICIPALITIES)
_MUNI_CITY = dict((code, city) for code, _pref, city in MUNICIPALITIES)
_MUNI_METRIC = {
    "nights": ("guest nights", "延べ宿泊者数"),
    "nightsfx": ("foreign guest nights", "外国人延べ宿泊者数"),
    "occ": ("room occupancy rate", "客室稼働率"),
}

NIGHTS, PERCENT = "person_nights", "percent"


def _order(family, area_index, category_index):
    return _FAMILY_RANK[family] * 1000000 + area_index * 1000 + category_index


def _describe(code):
    """(name_en, name_ja, unit, sort_order) for one series code."""
    parts = code.split(".")

    if parts[0] == "muni":
        mcode, metric = parts[1], parts[2]
        metric_en, metric_ja = _MUNI_METRIC[metric]
        pref_en, pref_ja = AREA_NAMES[_MUNI_PREF[mcode]]
        unit = PERCENT if metric == "occ" else NIGHTS
        return ("%s, %s — %s" % (_MUNI_CITY[mcode], pref_en, metric_en),
                "%s%s %s" % (pref_ja, _MUNI_CITY[mcode], metric_ja), unit,
                _order("muni", _MUNI_ORDER[mcode],
                       list(_MUNI_METRIC).index(metric)))

    head, area = parts[0], parts[1]
    area_en, area_ja = AREA_NAMES[area]
    index = AREA_INDEX[area]
    rest = parts[2:]

    if head == "occ":
        if not rest:
            return ("%s — room occupancy rate" % area_en,
                    "%s 客室稼働率" % area_ja, PERCENT, _order("occ", index, 0))
        kind = rest[1]
        return ("%s — room occupancy rate, %s" % (area_en, _TYPE_EN[kind]),
                "%s 客室稼働率 %s" % (area_ja, _TYPE_JA[kind]), PERCENT,
                _order("occ.type", index, _TYPE_ORDER[kind]))

    if head == "nightsfx":
        kind = rest[1]
        if rest[0] == "type":
            return ("%s — foreign guest nights, %s" % (area_en, _TYPE_EN[kind]),
                    "%s 外国人延べ宿泊者数 %s" % (area_ja, _TYPE_JA[kind]), NIGHTS,
                    _order("nightsfx.type", index, _TYPE_ORDER[kind]))
        if kind == "all":
            return ("%s — foreign guest nights, larger properties" % area_en,
                    "%s 外国人延べ宿泊者数（大規模施設）" % area_ja, NIGHTS,
                    _order("nightsfx.nat", index, 0))
        return ("%s — foreign guest nights, %s" % (area_en, _NAT_EN[kind]),
                "%s 外国人延べ宿泊者数 %s" % (area_ja, _NAT_JA[kind]), NIGHTS,
                _order("nightsfx.nat", index, _NAT_ORDER[kind] + 1))

    if not rest:
        return ("%s — guest nights" % area_en, "%s 延べ宿泊者数" % area_ja,
                NIGHTS, _order("nights", index, 0))
    if rest[0] == "jp":
        return ("%s — guest nights, Japanese guests" % area_en,
                "%s 日本人延べ宿泊者数" % area_ja, NIGHTS,
                _order("nights.jp", index, 0))
    if rest[0] == "fx":
        return ("%s — guest nights, foreign guests" % area_en,
                "%s 外国人延べ宿泊者数" % area_ja, NIGHTS,
                _order("nights.fx", index, 0))
    kind = rest[1]
    if rest[0] == "type":
        return ("%s — guest nights, %s" % (area_en, _TYPE_EN[kind]),
                "%s 延べ宿泊者数 %s" % (area_ja, _TYPE_JA[kind]), NIGHTS,
                _order("nights.type", index, _TYPE_ORDER[kind]))
    if rest[0] == "res":
        return ("%s — guest nights, %s" % (area_en, _RES_EN[kind]),
                "%s 延べ宿泊者数 %s" % (area_ja, _RES_JA[kind]), NIGHTS,
                _order("nights.res", index, list(_RES_EN).index(kind)))
    if rest[0] == "purpose":
        return ("%s — guest nights, %s" % (area_en, _PURPOSE_EN[kind]),
                "%s 延べ宿泊者数 %s" % (area_ja, _PURPOSE_JA[kind]), NIGHTS,
                _order("nights.purpose", index, list(_PURPOSE_EN).index(kind)))
    if rest[0] == "rooms":
        return ("%s — guest nights, %s properties" % (area_en, _BAND_EN[kind]),
                "%s 延べ宿泊者数 %s" % (area_ja, _BAND_JA[kind]), NIGHTS,
                _order("nights.rooms", index, _BAND_ORDER[kind]))
    raise ValidationError("no name for series code %r" % code)


# --- validate ----------------------------------------------------------------

# 292k at the first build and growing by roughly 1,600 a month, plus about
# 30k whenever another annual definitive workbook joins the bundle. A file
# that parses to materially less has lost workbooks or sheets.
MIN_OBSERVATIONS = 250_000

# A month of guest nights for any single series. The national headline runs
# near 55mn; the ceiling catches a units change, not an unusual month.
MAX_NIGHTS = 200_000_000

# An occupancy rate above 100 is rare but real (see validate()). The ceiling
# exists to catch a units change, not to second-guess the publisher.
MAX_OCCUPANCY = 150

# Reconciliation tolerances, as a share of the total being checked. Every
# figure is a rounded estimate grossed up from a sample, so adding 47 of them
# will not land exactly on the separately rounded national figure.
TOL_AREA_SUM = 0.005
TOL_SPLIT = 0.005
# Named nationalities never *exceed* their published total by more than
# rounding: the largest excess anywhere in the history is 30 person-nights,
# against categories rounded to the nearest 10. They routinely fall short of
# it, though, because the published total also contains guests of unknown
# nationality — normally 1-6% of a prefecture's foreign nights and far more in
# a thin cell. That residual is real and is disclosed on the release, never
# closed by scaling the named categories up.
TOL_NATIONALITY_EXCESS = 300


def _next_month(d):
    return (datetime.date(d.year + 1, 1, 1) if d.month == 12
            else datetime.date(d.year, d.month + 1, 1))


def validate(series, observations):
    if len(observations) < MIN_OBSERVATIONS:
        raise ValidationError("only %d observations parsed" % len(observations))

    units = dict((s["code"], s["unit"]) for s in series)
    by_period = {}
    seen = set()
    above_100 = 0
    for o in observations:
        key = (o["code"], o["period"])
        if key in seen:
            raise ValidationError("duplicate observation %s %s" % key)
        seen.add(key)
        value = o["value"]
        if units[o["code"]] == PERCENT:
            # An occupancy rate can exceed 100 in a thin cell: it is grossed
            # up from a sample, so a prefecture with a handful of city hotels
            # can print 104.3, as Tottori does for August 2011. Published
            # figures are never adjusted by us, so the band is wide enough to
            # catch a units error and nothing narrower, and the count of such
            # values is disclosed on the release.
            if not (0 <= value <= MAX_OCCUPANCY):
                raise ValidationError(
                    "%s %s: occupancy %s is outside the sanity band"
                    % (o["code"], o["period"], value))
            if value > 100:
                above_100 += 1
        elif not (0 <= value <= MAX_NIGHTS):
            raise ValidationError(
                "%s %s: %s guest nights outside the sanity band"
                % (o["code"], o["period"], value))
        by_period.setdefault(o["period"], {})[o["code"]] = value

    periods = sorted(by_period)
    if periods[0] != FIRST_TREND_PERIOD:
        raise ValidationError(
            "history starts %s, expected %s — the trend workbook is short"
            % (periods[0], FIRST_TREND_PERIOD))
    latest = periods[-1]
    if (datetime.date.today() - latest).days > 240:
        raise ValidationError(
            "latest period %s is implausibly old for a changed file" % latest)

    # No hole in the national headline anywhere in the run of history.
    month = FIRST_TREND_PERIOD
    while month <= latest:
        if "nights.%s" % NATIONAL not in by_period.get(month, {}):
            raise ValidationError("no national guest-nights value for %s" % month)
        month = _next_month(month)

    prefectures = ["nights.%s" % code for code, _ja, _en in PREFECTURES]
    checks = {"area_sum": 0, "split": 0, "nationality": 0}
    unknown_share = []
    for period, values in by_period.items():
        national = values.get("nights.%s" % NATIONAL)

        # The 47 prefectures partition the country: the transport-bureau rows
        # are a republication of the same nights and are never added in.
        if national and all(code in values for code in prefectures):
            total = sum(values[code] for code in prefectures)
            if abs(total - national) > TOL_AREA_SUM * national:
                raise ValidationError(
                    "%s: prefectures sum to %d against a national %d"
                    % (period, total, national))
            checks["area_sum"] += 1

        # Japanese plus foreign is the whole of guest nights, everywhere.
        for area in AREA_ORDER:
            whole = values.get("nights.%s" % area)
            jp = values.get("nights.%s.jp" % area)
            fx = values.get("nights.%s.fx" % area)
            if whole and jp is not None and fx is not None:
                if abs(jp + fx - whole) > TOL_SPLIT * whole:
                    raise ValidationError(
                        "%s %s: Japanese %d plus foreign %d against a total %d"
                        % (period, area, jp, fx, whole))
                checks["split"] += 1

        # Named nationalities sit inside their own (larger-property) total.
        for area in AREA_ORDER:
            base = values.get("nightsfx.%s.nat.all" % area)
            if not base:
                continue
            named = [v for code, v in values.items()
                     if code.startswith("nightsfx.%s.nat." % area)
                     and not code.endswith(".all")]
            if not named:
                continue
            if sum(named) - base > TOL_NATIONALITY_EXCESS:
                raise ValidationError(
                    "%s %s: nationalities sum to %d, above the published %d"
                    % (period, area, sum(named), base))
            unknown_share.append((base - sum(named)) / base)
            checks["nationality"] += 1

    if checks["area_sum"] < 150:
        raise ValidationError(
            "only %d months reconcile prefectures to the national figure"
            % checks["area_sum"])
    if checks["nationality"] < 1000:
        raise ValidationError(
            "only %d area-months reconcile the nationality split"
            % checks["nationality"])

    stats = getattr(parse, "stats", {})
    compared, mismatch = stats.get("compared", 0), stats.get("mismatch", 0)
    if compared and mismatch > 0.01 * compared:
        raise ValidationError(
            "%d of %d values published in two workbooks disagree — a column "
            "has probably been misread" % (mismatch, compared))

    families = {}
    for s in series:
        families[s["code"].split(".")[0]] = families.get(s["code"].split(".")[0], 0) + 1

    return {
        "series": len(series),
        "observations": len(observations),
        "months": len(periods),
        "latest_period": latest.isoformat(),
        "first_period": periods[0].isoformat(),
        "national_nights_latest": by_period[latest].get("nights.%s" % NATIONAL),
        "series_by_family": families,
        "months_reconciling_prefectures": checks["area_sum"],
        "area_months_reconciling_nationality": checks["nationality"],
        "area_months_reconciling_guest_split": checks["split"],
        "cross_source_compared": compared,
        "cross_source_mismatches": mismatch,
        "reliability_flagged_values": stats.get("flagged", 0),
        "occupancy_above_100": above_100,
        # The share of published foreign guest nights whose nationality the
        # survey does not identify. Disclosed, never absorbed into a category.
        "unknown_nationality_share_median": (
            round(sorted(unknown_share)[len(unknown_share) // 2], 4)
            if unknown_share else None),
        "unknown_nationality_share_max": (
            round(max(unknown_share), 4) if unknown_share else None),
        "unregistered_municipalities": stats.get("unregistered_municipalities", []),
        "stratification_break": BREAK_PERIOD.isoformat(),
    }


# --- presentation ------------------------------------------------------------

PRESENTATION = {
    "credit_line": ("Source: Japan Tourism Agency, Accommodation Survey "
                    "(観光庁『宿泊旅行統計調査』)."),
    # Published about two months in arrears, so a healthy dataset is always a
    # couple of months behind today.
    "stale_after_days": 150,
    "accommodation": {
        "headline": "nights.%s" % NATIONAL,
        "national": NATIONAL,
        "prefectures": [code for code, _ja, _en in PREFECTURES],
        "bureaus": [code for code, _ja, _en in BUREAUS],
        "area_names": dict((code, name[0]) for code, name in AREA_NAMES.items()),
        "facility_types": [{"code": c, "label": e} for c, _j, e in FACILITY_TYPES],
        "room_bands": [{"code": c, "label": e} for c, _j, e in ROOM_BANDS],
        "nationalities": [{"code": c, "label": e, "era": era}
                          for c, _j, e, era in NATIONALITIES],
        "purposes": [{"code": c, "label": e} for c, _j, e in PURPOSES],
        "residence": [{"code": c, "label": e} for c, _j, e in RESIDENCE],
        "municipalities": [{"code": c, "label": city, "prefecture": pref,
                            "prefecture_label": AREA_NAMES[pref][0]}
                           for c, pref, city in MUNICIPALITIES],
        "baseline_year": 2019,
        "break_period": BREAK_PERIOD.isoformat(),
        "break_note": (
            "From January 2026 the survey stratifies properties by room count "
            "rather than employee count, and reports 24 visitor nationalities "
            "rather than 21. Facility-size series begin at the break; the "
            "residual “Other” nationality is carried as two separate "
            "series because it means different things on either side."),
        "feature_areas": ["13", "27", "26", "01", "47", "40"],
        "feature_nationalities": ["cn", "kr", "tw", "hk", "us", "au"],
    },
}


# The dataset's card. Guest nights are a count and occupancy is a published
# rate; every growth, share, mix and recovery figure on the tourism pages is
# computed there and its formula is recorded here.
MANIFEST = {
    "id": DATASET["slug"],
    "section": "tourism",
    "name": {"en": "Accommodation Survey — guest nights and occupancy",
             "ja": "宿泊旅行統計調査"},
    "shape": "series",
    "summary": (
        "Monthly guest nights and room occupancy for Japan, its 47 prefectures "
        "and 10 transport-bureau regions from January 2011, split into "
        "Japanese and foreign guests and by hotel type; from January 2019 also "
        "foreign guest nights by visitor nationality and the leisure/business "
        "and in-prefecture/out-of-prefecture splits; from January 2026 also "
        "facility-size bands and 175 named municipalities."),
    "source": {
        "publisher": DATASET["agency"],
        "publisher_ja": DATASET["agency_ja"],
        "document": SOURCE["name"],
        "url": SOURCE["url"],
        "credit": PRESENTATION["credit_line"],
        "license_note": SOURCE["license_note"],
    },
    "keys": ["series_code", "period"],
    "frequency": DATASET["frequency"],
    "vintage": {
        "unit": "release", "as_of_basis": "release-in-force",
        "as_of_supported": True, "history_from": "2011-01",
        "stale_after_days": PRESENTATION["stale_after_days"],
    },
    "measures": [
        {"id": "index", "label": "Guest nights, person-nights",
         "unit": "person_nights", "trust": "official"},
        {"id": "occupancy", "label": "Room occupancy rate", "unit": "%",
         "trust": "official"},
        {"id": "yoy", "label": "Year over year", "unit": "%", "trust": "derived",
         "calc": "(value[t] / value[t−12 months] − 1) × 100, from published values."},
        {"id": "occupancy_change_pp", "label": "Occupancy change, year over year",
         "unit": "pp", "trust": "derived",
         "calc": ("occupancy[t] − occupancy[t−12 months], in percentage points. "
                  "An occupancy rate is a ratio: it is differenced, never divided, "
                  "and never averaged across areas by us.")},
        {"id": "recovery", "label": "Recovery vs the same month of the baseline year",
         "unit": "%", "trust": "derived",
         "calc": ("recovery[t] = (guest nights[t] / guest nights[same month of 2019]) "
                  "× 100. 100 = the same month of 2019, the last full year before "
                  "the border closed.")},
        {"id": "foreign_share", "label": "Foreign share of guest nights", "unit": "%",
         "trust": "derived",
         "calc": ("share[area, t] = (foreign guest nights[area, t] / guest "
                  "nights[area, t]) × 100, both published counts for the same "
                  "month and the same universe.")},
        {"id": "nationality_share", "label": "Share of foreign guest nights by nationality",
         "unit": "%", "trust": "derived",
         "calc": ("share[nationality, t] = (foreign guest nights[nationality, t] / "
                  "foreign guest nights[larger properties, t]) × 100. The "
                  "denominator is the nationality table's own published total, "
                  "which covers larger properties only — not the all-properties "
                  "foreign guest nights, which the named nationalities do not sum to.")},
        {"id": "area_contrib_pp", "label": "Contribution of an area to national growth",
         "unit": "pp", "trust": "derived",
         "calc": ("contribution[area, t] = (guest nights[area, t] − guest "
                  "nights[area, t−12]) / guest nights[All Japan, t−12] × 100, in "
                  "percentage points. The residual is growth[All Japan, t] − Σ "
                  "contribution[named areas, t] and is always shown.")},
    ],
    "endpoints": {
        "series": "/api/v1/%s/observations" % DATASET["slug"],
        "accommodation": "/api/v1/%s/accommodation" % DATASET["slug"],
        "releases": "/api/v1/%s/releases" % DATASET["slug"],
        "revisions": "/api/v1/%s/revisions" % DATASET["slug"],
    },
    "capabilities": ["series"],
    "cite": "/accommodation.html",
    "page": "/accommodation.html",
    "notes": [
        "Guest nights are person-nights and room occupancy is a percentage. "
        "They are different measures: never rank, sum or average them together.",
        "Estimates grossed up from a sample survey. The Agency publishes a "
        "standard error rate per prefecture, from about 1% at the national "
        "headline to near 30% for the smallest properties in a thin prefecture, "
        "and marks individual weak cells; marked values are kept and counted, "
        "never silently dropped.",
        "Three release stages: a first preliminary covering national totals "
        "only, a fuller second preliminary about a month later, then the annual "
        "definitive figures the following year. Unlike visitor arrivals, this "
        "survey genuinely revises, so its point-in-time vintages carry real "
        "information.",
        "From January 2026 properties are stratified by room count instead of "
        "employee count. Facility-size series therefore begin in 2026 and the "
        "pre-2026 employee bands are deliberately not carried.",
        "Foreign guest nights by nationality cover larger properties only and do "
        "not sum to the all-properties foreign guest nights. Use the "
        "nationality table's own total as the denominator.",
        "The transport-bureau regions are a republication of the same nights as "
        "the prefectures. Never add a region to its prefectures.",
        "Municipality names are carried in Japanese with the prefecture "
        "romanised; the Agency publishes no romanisation and we do not invent one.",
    ],
}
