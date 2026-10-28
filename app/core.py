"""Local, evidence-preserving media operations. No remote publishing side effects."""
from __future__ import annotations
import csv, hashlib, io, json, os, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# ZoneInfo, or the built-in US Pacific rules on Windows (no time zone database there)
from spt.server.timezones import pacific
PACIFIC = pacific()
DB = Path(os.environ.get('MEDIA_DB', str(ROOT / 'data' / 'media.sqlite3')))
PLATFORMS = [
 {'id':'instagram','name':'Instagram','kind':'social','accent':'#df437d','short':'IG'},
 {'id':'facebook','name':'Facebook','kind':'social','accent':'#1877f2','short':'FB'},
 {'id':'tiktok','name':'TikTok','kind':'social','accent':'#142433','short':'TK'},
 {'id':'youtube','name':'YouTube','kind':'social','accent':'#e3453c','short':'YT'},
 {'id':'google_business','name':'Google Business Profile','kind':'social','accent':'#34a568','short':'GB'},
 {'id':'google_ads','name':'Google Ads','kind':'ads','accent':'#d99717','short':'AD'},
 {'id':'xiaohongshu','name':'rednote','kind':'social','accent':'#e9364c','short':'rednote'},
 {'id':'yelp','name':'Yelp','kind':'social','accent':'#d32323','short':'Yelp'},
]
CONNECTORS = [
 {'id':'metricool','name':'Metricool','status':'未授权','coverage':'Instagram · Facebook · TikTok · YouTube · Google Ads（分析）','description':'多账号、日历与分析流程的产品参考。本地使用不需要订阅；尚未接入其账号或服务。','url':'https://help.metricool.com/faqs-about-the-metricool-mcp-1i3w0'},
 {'id':'postiz','name':'Postiz','status':'未授权','coverage':'Instagram · Facebook · TikTok · YouTube · Google Business Profile','description':'结构化任务与上传适配的技术参考，可选服务。不作为本地工作台使用前提；没有已接通的真实发布账号。','url':'https://docs.postiz.com/general/analytics'},
 {'id':'xiaohongshu','name':'rednote','status':'软件内发布','coverage':'账号 · 上传 · 发布记录 · CSV复盘','description':'原生版支持官方账号页、后台媒体交接与人工提交；实际结果人工登记，运营数据通过CSV归档。','url':'https://creator.rednote.com/new/note-manager'},
]
SOCIAL_FIELDS = ['platform','account','post_id','title','url','published_at','observed_at','views','reach','likes','comments','shares','saves','clicks']
ADS_FIELDS = ['platform','account','campaign','date','impressions','clicks','spend','conversions','currency']
NUMBERS = ['views','reach','likes','comments','shares','saves','clicks','impressions','spend','conversions']
ALIASES = {'平台':'platform','账号':'account','作品ID':'post_id','笔记ID':'post_id','标题':'title','链接':'url','发布时间':'published_at','采集时间':'observed_at','播放量':'views','观看次数':'views','触达人数':'reach','点赞':'likes','点赞数':'likes','评论':'comments','评论数':'comments','分享':'shares','分享数':'shares','收藏':'saves','收藏数':'saves','点击':'clicks','点击数':'clicks','广告系列':'campaign','日期':'date','展示次数':'impressions','花费':'spend','转化':'conversions','币种':'currency'}
PLATFORM_ALIASES={'ig':'instagram','ins':'instagram','fb':'facebook','tk':'tiktok','yt':'youtube','google business profile':'google_business','google my business':'google_business','google ads':'google_ads','小红书':'xiaohongshu','xhs':'xiaohongshu','rednote':'xiaohongshu'}

class ValidationError(ValueError): pass

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def connect():
 DB.parent.mkdir(parents=True, exist_ok=True)
 c=sqlite3.connect(DB,timeout=10); c.row_factory=sqlite3.Row
 c.execute('PRAGMA journal_mode=WAL')
 c.executescript('''CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY, kind TEXT NOT NULL, dataset TEXT NOT NULL, natural_key TEXT NOT NULL, observed_at TEXT NOT NULL, payload TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, platform TEXT NOT NULL, handle TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(platform,handle));
 CREATE TABLE IF NOT EXISTS imports (id TEXT PRIMARY KEY, filename TEXT, kind TEXT, created_at TEXT, rows_count INTEGER);
 CREATE TABLE IF NOT EXISTS audit (id TEXT PRIMARY KEY, created_at TEXT, action TEXT, detail TEXT);
 CREATE TABLE IF NOT EXISTS core_schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL);''')
 migration='draft_platform_variants_v1'
 if not c.execute('SELECT 1 FROM core_schema_migrations WHERE name=?',(migration,)).fetchone():
  try:
   with c:
    c.execute('BEGIN IMMEDIATE')
    if not c.execute('SELECT 1 FROM core_schema_migrations WHERE name=?',(migration,)).fetchone():
     for row in c.execute('SELECT id,payload FROM drafts').fetchall():
      draft=json.loads(row['payload'])
      if isinstance(draft,dict) and 'platform_variants' not in draft:
       draft['platform_variants']={}
       c.execute('UPDATE drafts SET payload=? WHERE id=?',(json.dumps(draft,ensure_ascii=False),row['id']))
     c.execute('INSERT INTO core_schema_migrations VALUES(?,?)',(migration,now()))
  except Exception:
   c.close()
   raise
 return c

def audit(c,action,detail):
 c.execute('INSERT INTO audit VALUES(?,?,?,?)',(uuid.uuid4().hex,now(),action,json.dumps(detail,ensure_ascii=False)))

def iso(value,field):
 value=str(value).strip()
 if not value: raise ValidationError(f'{field} 不能为空')
 try:
  d=datetime.fromisoformat(value.replace('Z','+00:00'))
  if d.tzinfo is None: d=d.replace(tzinfo=PACIFIC)
  return d.astimezone(timezone.utc).isoformat(timespec='seconds')
 except (ValueError,OverflowError): raise ValidationError(f'{field} 日期格式无效：{value}')

def number(value,field):
 if value is None or str(value).strip() in ('','—','-','null','N/A'): return None
 try:
  n=float(str(value).replace(',','').strip())
  if not (0 <= n < 1e15): raise ValueError()
  if field not in ('spend','conversions') and n != int(n): raise ValueError()
  return n if field in ('spend','conversions') else int(n)
 except (ValueError,OverflowError): raise ValidationError(f'{field} 必须是非负数字（留空表示未知）')

def platform(value):
 p=str(value).strip().lower(); p=PLATFORM_ALIASES.get(p,p)
 if p not in {x['id'] for x in PLATFORMS}: raise ValidationError(f'不支持的平台：{value}')
 return p

def required(row,field):
 raw=row.get(field,'')
 if raw is None or not isinstance(raw,str): raise ValidationError(f'{field} 必须是非空文本')
 v=raw.strip()
 if not v: raise ValidationError(f'缺少 {field}')
 if len(v)>(30000 if field=='body' else 4000): raise ValidationError(f'{field} 过长')
 return v

def clean_record(row,kind,source):
 r={ALIASES.get(k.strip(),k.strip()):str(v or '').strip() for k,v in row.items() if k is not None}
 p=platform(required(r,'platform')); account=required(r,'account')
 item={'platform':p,'account':account,'source':source}
 if kind=='social':
  if p=='google_ads': raise ValidationError('Google Ads 请使用广告数据模板')
  item.update({k:r.get(k,'') for k in ['title','url']})
  if item['url'] and not item['url'].startswith(('https://','http://')): raise ValidationError('链接必须以 https:// 或 http:// 开头')
  item['post_id']=required(r,'post_id'); item['published_at']=iso(required(r,'published_at'),'published_at')
  item['observed_at']=iso(required(r,'observed_at'),'observed_at')
  if item['observed_at'] < item['published_at']: raise ValidationError('采集时间不能早于发布时间')
  for f in ['views','reach','likes','comments','shares','saves','clicks']: item[f]=number(r.get(f),f)
  natural=json.dumps([p,account,item['post_id']],ensure_ascii=False); observed=item['observed_at']
 else:
  if p!='google_ads': raise ValidationError('当前广告数据范围为 Google Ads')
  item['campaign']=required(r,'campaign')
  try: item['date']=datetime.strptime(required(r,'date'),'%Y-%m-%d').date().isoformat()
  except ValueError: raise ValidationError('date 请使用 YYYY-MM-DD')
  for f in ['impressions','clicks','spend','conversions']: item[f]=number(r.get(f),f)
  item['currency']=required(r,'currency').upper()
  if len(item['currency'])!=3 or not item['currency'].isalpha(): raise ValidationError('currency 使用三字母币种，如 USD')
  natural=json.dumps([p,account,item['campaign'],item['date'],item['currency']],ensure_ascii=False); observed=item['date']
 item['id']=hashlib.sha256((kind+'|'+natural+'|'+observed).encode()).hexdigest()[:24]
 return item,natural,observed

def import_csv(kind,csv_text,filename='数据导入.csv'):
 if kind not in ('social','ads'): raise ValidationError('kind 必须为 social 或 ads')
 if not isinstance(csv_text,str) or len(csv_text.encode())>5_000_000: raise ValidationError('CSV 必须小于 5 MB')
 reader=csv.DictReader(io.StringIO(csv_text.lstrip('\ufeff')))
 if not reader.fieldnames: raise ValidationError('CSV 缺少表头')
 canonical=[ALIASES.get(x.strip(),x.strip()) for x in reader.fieldnames]
 if len(canonical)!=len(set(canonical)): raise ValidationError('CSV 存在重复字段')
 rows=list(reader)
 if not rows or len(rows)>10000: raise ValidationError('每次请导入 1–10000 行')
 source=Path(str(filename)).name[:160] or '数据导入.csv'
 records=[]; import_id=uuid.uuid4().hex; imported_at=now()
 for i,row in enumerate(rows,2):
  if None in row: raise ValidationError(f'第 {i} 行列数超过表头')
  try:
   record,natural,observed=clean_record(row,kind,source)
   record.update(source_id=import_id,source_row=i,imported_at=imported_at)
   records.append((record,natural,observed))
  except ValidationError as e: raise ValidationError(f'第 {i} 行：{e}')
 inserted=updated=0
 with connect() as c:
  for record,natural,observed in records:
   exists=c.execute('SELECT 1 FROM observations WHERE id=?',(record['id'],)).fetchone()
   updated+=int(bool(exists)); inserted+=int(not exists)
   c.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?,?)',(record['id'],kind,'real',natural,observed,json.dumps(record,ensure_ascii=False)))
  raw_dir=DB.parent/'imports'; raw_dir.mkdir(exist_ok=True)
  (raw_dir/(import_id+'.csv')).write_text(csv_text,encoding='utf-8')
  (raw_dir/(import_id+'.json')).write_text(json.dumps({'id':import_id,'filename':source,'kind':kind,'imported_at':imported_at,'rows':len(records),'sha256':hashlib.sha256(csv_text.encode()).hexdigest()},ensure_ascii=False,indent=2),encoding='utf-8')
  c.execute('INSERT INTO imports VALUES(?,?,?,?,?)',(import_id,source,kind,imported_at,len(records)))
  audit(c,'import_metrics',{'filename':source,'kind':kind,'inserted':inserted,'updated':updated})
 return {'imported':inserted,'updated':updated,'rows':len(records),'message':'已保存；同一作品的概览只使用最新采集快照，重复导入不会重复累计。'}

def template(kind):
 if kind not in ('social','ads'): raise ValidationError('未知模板')
 o=io.StringIO(); w=csv.writer(o); w.writerow(SOCIAL_FIELDS if kind=='social' else ADS_FIELDS)
 return '\ufeff'+o.getvalue()

def demo():
 posts=[]
 base=[('instagram','15秒产品细节：把使用场景拍清楚',18420,840,63,101,183),('tiktok','开头3秒展示成品，再讲过程',32600,1530,119,286,171),('youtube','AI 短片的声音设计过程',9800,462,54,60,42),('facebook','从一张产品图到完整视觉故事',7900,312,38,75,29),('xiaohongshu','一套可复用的角色视觉制作记录',12600,638,87,96,492),('google_business','本周作品与服务更新',920,27,4,5,3),('instagram','同一个故事，两种镜头语言',11300,482,35,74,101),('tiktok','幕后制作的一个小技巧',21600,806,77,128,88)]
 for i,(p,t,v,l,c,s,sv) in enumerate(base):
  posts.append({'id':f'demo-{i}','post_id':f'demo-{i}','platform':p,'account':'演示创作账号','title':t,'url':'','published_at':f'2026-10-{8+i:02d}T17:00:00+00:00','observed_at':'2026-10-16T07:00:00+00:00','views':v,'reach':None,'likes':l,'comments':c,'shares':s,'saves':sv,'clicks':None,'source':'内置演示数据（虚构）'})
 ads=[{'id':'demo-ad-1','platform':'google_ads','account':'演示广告账户','campaign':'作品集引流 · 演示','date':'2026-10-15','impressions':15400,'clicks':462,'spend':138.6,'conversions':12,'currency':'USD','source':'内置演示数据（虚构）'}]
 return posts,ads

def total(rows,key):
 values=[r.get(key) for r in rows if r.get(key) is not None]
 return round(sum(values),4) if values else None

def summary(posts,ads):
 complete=[p for p in posts if p.get('views') and all(p.get(k) is not None for k in ['likes','comments','shares','saves'])]
 engagement=sum(sum(p[k] for k in ['likes','comments','shares','saves']) for p in complete)
 denominator=sum(p['views'] for p in complete)
 currencies=sorted({r['currency'] for r in ads if r.get('spend') is not None})
 spend={cur:total([a for a in ads if a['currency']==cur],'spend') for cur in currencies}
 known_interactions=[sum(p[k] for k in ['likes','comments','shares','saves']) for p in posts if all(p.get(k) is not None for k in ['likes','comments','shares','saves'])]
 return {'post_count':len(posts),'views':total(posts,'views'),'engagements':sum(known_interactions) if known_interactions else None,'engagement_rate':round(engagement/denominator*100,3) if denominator else None,'engagement_sample_count':len(complete),'ad_spend':spend[currencies[0]] if len(currencies)==1 else None,'currency':currencies[0] if len(currencies)==1 else None,'spend_by_currency':spend,'ad_clicks':total(ads,'clicks'),'ad_conversions':total(ads,'conversions'),'source_count':len({p['source'] for p in posts+ads})}

def account_key(p,handle): return hashlib.sha256((p+'|'+handle).encode()).hexdigest()[:20]

def create_account(data):
 p=platform(required(data,'platform')); handle=required(data,'handle')
 a={'id':account_key(p,handle),'platform':p,'handle':handle,'name':required(data,'name'),'brand':str(data.get('brand','未分组')).strip() or '未分组','notes':str(data.get('notes',''))[:4000],'status':'本地账号档案 · 未授权','metric_count':0}
 with connect() as c:
  if c.execute('SELECT 1 FROM accounts WHERE platform=? AND handle=?',(p,handle)).fetchone(): raise ValidationError('同平台的此账号已存在')
  c.execute('INSERT INTO accounts VALUES(?,?,?,?)',(a['id'],p,handle,json.dumps(a,ensure_ascii=False))); audit(c,'create_account',{'id':a['id'],'platform':p})
 return {'account':a}

def update_account(identifier,data):
 with connect() as c:
  r=c.execute('SELECT payload FROM accounts WHERE id=?',(identifier,)).fetchone()
  if r: a=json.loads(r['payload'])
  else:
   a=next((a for a in state()['accounts'] if a['id']==identifier),None)
   if not a: raise ValidationError('账号档案不存在')
   c.execute('INSERT INTO accounts VALUES(?,?,?,?)',(a['id'],a['platform'],a['handle'],json.dumps(a,ensure_ascii=False)))
  for field in ['name','brand','notes']:
   if field in data:
    if data[field] is None or not isinstance(data[field],str): raise ValidationError(f'{field} 必须是文本')
    a[field]=data[field].strip()[:4000]
  if not a['name']: raise ValidationError('账号名称不能为空')
  a['brand']=a.get('brand') or '未分组'
  c.execute('UPDATE accounts SET payload=? WHERE id=?',(json.dumps(a,ensure_ascii=False),identifier)); audit(c,'update_account',{'id':identifier})
 return {'account':a}

def state(dataset='real',account_id=None):
 if dataset not in ('real','demo'): raise ValidationError('dataset 必须为 real 或 demo')
 with connect() as c:
  raw=c.execute('SELECT * FROM observations WHERE dataset=? ORDER BY observed_at ASC',('real',)).fetchall()
  drafts=[json.loads(r['payload']) for r in c.execute('SELECT payload FROM drafts ORDER BY rowid DESC')]
  imports=[dict(r) for r in c.execute('SELECT * FROM imports ORDER BY created_at DESC LIMIT 50')]
  registered=[json.loads(r['payload']) for r in c.execute('SELECT payload FROM accounts ORDER BY rowid')]
 for d in drafts:
  d.setdefault('media_ids',[])
  d.setdefault('platform_variants',{})
 if dataset=='demo': posts,ads=demo(); drafts=[]; imports=[]
 else:
  latest={}
  for r in raw: latest[(r['kind'],r['natural_key'])]=json.loads(r['payload'])
  posts=[p for (kind,_),p in latest.items() if kind=='social']; ads=[p for (kind,_),p in latest.items() if kind=='ads']
 accounts=[] if dataset=='demo' else registered
 for a in accounts: a['metric_count']=0
 mapping={a['id']:a for a in accounts}
 for row in posts+ads:
  aid=account_key(row['platform'],row['account']); row['account_id']=aid
  if aid not in mapping:
   a={'id':aid,'platform':row['platform'],'name':row['account'],'handle':row['account'],'brand':'演示品牌' if dataset=='demo' else '未分组','status':'演示' if dataset=='demo' else 'CSV 数据账号 · 未授权','notes':'','metric_count':0}
   accounts.append(a); mapping[aid]=a
  mapping[aid]['metric_count']=mapping[aid].get('metric_count',0)+1
 if account_id:
  if account_id not in mapping: raise ValidationError('未找到该账号')
  posts=[r for r in posts if r['account_id']==account_id]; ads=[r for r in ads if r['account_id']==account_id]
  drafts=[d for d in drafts if account_id in d.get('account_ids',[])]
 return {'dataset':dataset,'accounts':accounts,'posts':sorted(posts,key=lambda x:x['published_at'],reverse=True),'ads':ads,'drafts':drafts,'imports':imports,'summary':summary(posts,ads),'platforms':PLATFORMS,'connectors':CONNECTORS,'updated_at':now(),'timezone':'America/Los_Angeles','remote_publishing_enabled':False}

def platform_variants(value):
 if not isinstance(value,dict): raise ValidationError('platform_variants 必须是以平台 ID 为键、正文为值的对象')
 allowed={p['id'] for p in PLATFORMS if p['kind']=='social'}
 result={}
 for key,body in value.items():
  if not isinstance(key,str) or key not in allowed: raise ValidationError('平台改写只支持已知内容平台 ID，不能包含 Google Ads')
  if not isinstance(body,str): raise ValidationError('平台改写正文必须是字符串；留空字符串表示使用主稿')
  body=body.strip()
  if len(body)>30000: raise ValidationError('每个平台改写正文最多 30000 字')
  result[key]=body
 return result

def draft_values(data,previous=None):
 d=dict(previous or {})
 for key in ['title','body','platforms','scheduled_at','account_ids','media_ids','platform_variants']:
  if key in data: d[key]=data[key]
 d['title']=required(d,'title'); d['body']=required(d,'body')
 if not d['title'] or len(d['title'])>300: raise ValidationError('标题需 1–300 字')
 if not d['body'] or len(d['body'])>30000: raise ValidationError('正文需 1–30000 字')
 d['platform_variants']=platform_variants(d.get('platform_variants',{}))
 ids=d.get('account_ids',[])
 if not isinstance(ids,list) or any(not isinstance(i,str) or not i.strip() for i in ids): raise ValidationError('account_ids 必须是非空字符串 ID 列表')
 d['account_ids']=list(dict.fromkeys(ids))
 if d['account_ids']:
  available={a['id']:a for a in state('real')['accounts']}
  if any(i not in available for i in d['account_ids']): raise ValidationError('部分目标账号不存在')
  d['platforms']=[available[i]['platform'] for i in d['account_ids']]
 if not isinstance(d.get('platforms'),list) or not d['platforms']: raise ValidationError('至少选择一个内容平台')
 d['platforms']=list(dict.fromkeys(platform(p) for p in d['platforms']))
 if 'google_ads' in d['platforms']: raise ValidationError('Google Ads 是广告数据频道，不支持内容发帖')
 media_ids=d.get('media_ids',[])
 if not isinstance(media_ids,list) or any(not isinstance(i,str) or not i.strip() for i in media_ids): raise ValidationError('media_ids 必须是非空字符串 ID 列表')
 d['media_ids']=list(dict.fromkeys(media_ids))
 if d['media_ids']:
  if __package__: from . import media_uploads
  else: import media_uploads
  available_media={job['id'] for job in media_uploads.snapshot()['jobs']}
  if any(i not in available_media for i in d['media_ids']): raise ValidationError('部分素材不存在，请重新选择')
 if d.get('scheduled_at'): d['scheduled_at']=iso(d['scheduled_at'],'scheduled_at')
 else: d['scheduled_at']=''
 return d

def create_draft(data):
 d=draft_values(data); d.update({'id':uuid.uuid4().hex,'status':'draft','created_at':now(),'updated_at':now(),'delivery':'local_only'})
 with connect() as c:
  c.execute('INSERT INTO drafts VALUES(?,?)',(d['id'],json.dumps(d,ensure_ascii=False))); audit(c,'create_draft',{'id':d['id']})
 return {'draft':d}

def update_draft(identifier,data):
 with connect() as c:
  row=c.execute('SELECT payload FROM drafts WHERE id=?',(identifier,)).fetchone()
  if not row: raise ValidationError('草稿不存在')
  previous=json.loads(row['payload']); d=draft_values(data,previous)
  variants_changed=d['platform_variants']!=previous.get('platform_variants',{})
  changed=any(d.get(k)!=previous.get(k) for k in ['title','body','platforms','scheduled_at','account_ids']) or d['media_ids']!=previous.get('media_ids',[]) or variants_changed
  default_status='review' if variants_changed and previous['status']=='approved' else ('draft' if changed else previous['status'])
  desired=data.get('status',default_status)
  if desired not in ('draft','review','approved'): raise ValidationError('不支持此状态；本地工作台不能把草稿标记为已发布')
  if desired=='approved' and previous['status'] not in ('review','approved'): raise ValidationError('请先提交审核，再标记批准')
  if desired=='approved' and changed: raise ValidationError('修改后的内容须重新提交审核')
  if variants_changed and previous['status']=='approved': desired='review'
  d['status']=desired; d['updated_at']=now()
  c.execute('UPDATE drafts SET payload=? WHERE id=?',(json.dumps(d,ensure_ascii=False),identifier)); audit(c,'update_draft',{'id':identifier,'status':desired,'content_changed':changed,'platform_variants_changed':variants_changed})
 return {'draft':d}

def analyze(dataset='real',account_id=None,platform_id=None):
 s=state(dataset,account_id); findings=[]
 if platform_id:
  selected=platform(platform_id)
  s['posts']=[p for p in s['posts'] if p['platform']==selected]; s['ads']=[a for a in s['ads'] if a['platform']==selected]
  s['summary']=summary(s['posts'],s['ads'])
 for platform_row in PLATFORMS:
  rows=[p for p in s['posts'] if p['platform']==platform_row['id'] and p.get('views') is not None]
  if rows:
   best=max(rows,key=lambda x:x['views']); n=len(rows)
   findings.append({'title':f"{platform_row['name']}：当前导入样本播放最高的内容",'detail':f"《{best['title'] or best['post_id']}》有 {best['views']:,} 次播放；比较范围为该平台 {n} 条导入内容。" ,'evidence':f"作品 {best['post_id']} · {best['source']} · 采集 {best['observed_at']}"})
 for currency,spend in s['summary']['spend_by_currency'].items():
  rows=[a for a in s['ads'] if a['currency']==currency]; paired=[a for a in rows if a.get('spend') is not None and a.get('clicks') is not None]; costs=sum(a['spend'] for a in paired); clicks=sum(a['clicks'] for a in paired)
  findings.append({'title':f'Google Ads · {currency}', 'detail':f'已导入花费 {spend:,.2f} {currency}。'+(f'花费和点击均完整的 {len(paired)} 行，平均每次点击成本 {costs/clicks:.2f} {currency}。' if clicks else '点击数据不足，暂不计算 CPC。'),'evidence':f"{len(rows)} 行日数据；币种单独汇总。"})
 if not findings: findings=[{'title':'还没有可分析的真实数据','detail':'先从平台或 Metricool 导出数据，按模板导入。也可以切换到演示数据体验。','evidence':'真实数据库当前为空，未调用任何平台账号。'}]
 return {'summary':s['summary'],'findings':findings,'limitations':['这是基于导入数据的规则复盘，未调用 AI 模型。','演示数据与真实数据隔离；不会将示例表现当作真实成绩。','播放量不等于跨平台去重用户；互动率仅用点赞、评论、分享、收藏和播放均完整的作品计算。','每篇内容用最新采集快照，不能据此推断每天增长、完播率、最佳发布时间或因果关系。','Google Ads 为数据观察；本工具不创建广告或花费预算。']}

def research():
 p=ROOT/'docs'/'research.json'
 if p.exists(): return json.loads(p.read_text(encoding='utf-8'))
 return {'recommendation':'以 Metricool 为海外数据与发布体验参考，Postiz 为 AI 接口参考；小红书使用独立适配。','checked_at':'2026-10-16','products':[],'sources':[]}

def export_drafts():
 s=state('real'); targets={i for d in s['drafts'] for i in d.get('account_ids',[])}
 media_ids=list(dict.fromkeys(i for d in s['drafts'] for i in d['media_ids']))
 media_assets=[]
 if media_ids:
  if __package__: from . import media_uploads
  else: import media_uploads
  available_media={job['id']:job for job in media_uploads.snapshot()['jobs']}
  if any(i not in available_media for i in media_ids): raise ValidationError('部分草稿素材不存在，请重新选择后导出')
  media_assets=[{key:available_media[i].get(key) for key in ['id','name','path','size','status','provider_id','provider_path']} for i in media_ids]
 return {'schema_version':1,'exported_at':now(),'timezone':'America/Los_Angeles','delivery':'local_only','published':False,'accounts':[a for a in s['accounts'] if a['id'] in targets],'platforms':PLATFORMS,'drafts':s['drafts'],'media_assets':media_assets}

def dispatch(action,args):
 if action=='state': return state(args.get('dataset','real'),args.get('account_id'))
 if action=='research': return research()
 if action=='analyze': return analyze(args.get('dataset','real'),args.get('account_id'),args.get('platform_id'))
 if action=='create_account': return create_account(args)
 if action=='update_account': return update_account(args['id'],{k:v for k,v in args.items() if k!='id'})
 if action=='create_draft': return create_draft(args)
 if action=='update_draft': return update_draft(args['id'],{k:v for k,v in args.items() if k!='id'})
 if action=='import_metrics': return import_csv(args['kind'],args['csv_text'],args.get('filename','AI导入.csv'))
 if action=='export_drafts': return export_drafts()
 raise ValidationError(f'未知操作：{action}')
