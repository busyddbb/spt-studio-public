"""Dependency-free stdio MCP for the local media workspace; no publishing tools."""
from __future__ import annotations
import json,sys
import core, media_uploads, planning

def schema(props,required=None): return {'type':'object','properties':props,'required':required or [],'additionalProperties':False}
S={'type':'string'}; DATASET={'type':'string','enum':['real','demo'],'default':'real'}
STRING_ARRAY={'type':'array','items':S}
PLATFORM_VARIANTS={'type':'object','propertyNames':{'enum':[p['id'] for p in core.PLATFORMS if p['kind']=='social']},'additionalProperties':{'type':'string','maxLength':30000},'description':'按平台 ID 保存独立正文；空字符串沿用 body。整体替换，省略保留，Google Ads 不支持。'}
PILLARS={'type':'array','items':S,'minItems':3,'maxItems':3}
QUESTION_FIELDS={'account_id':S,'question':S,'context':S,'source_type':{'type':'string','enum':['search','comment','work_record','other']},'source_url':S,'source_note':S,'pillar':S,'materials':S,'material_ready':{'type':'boolean'},'priority':{'type':'integer','minimum':1,'maximum':3},'status':{'type':'string','enum':['inbox','selected','parked']}}
ITEM_FIELDS={'id':S,'account_id':S,'question_id':{'type':['string','null']},'title':S,'content_type':{'type':'string','enum':['method','case','process','template']},'pillar':S,'material_plan':S,'material_ready':{'type':'boolean'},'reader_action':S,'expected_feedback':S,'variable':S,'body':S,'media_ids':STRING_ARRAY}
OBSERVATION_FIELDS={'id':S,'account_id':S,'post_url':S,'published_at':S,'observed_at':S,'reader_question':S,'next_answer':S,'next_materials':S,'note':S,**{key:{'type':['number','null'],'minimum':0} for key in ['views','impressions','saves','comments','follows','production_minutes']}}
PLANNING_TOOLS=[
 ('planning_workspace','读取指定账号的定位、真实问题、12篇内容计划和人工观察记录。账号相互隔离。',schema({'account_id':S},['account_id']),True),
 ('save_strategy','保存账号定位与三个内容栏目，不推测用户受众或材料。',schema({'account_id':S,'audience':S,'scenario':S,'problem':S,'materials':S,'pillars':PILLARS},['account_id','audience','scenario','problem','materials','pillars']),False),
 ('add_question','记录有上下文的问题及出处，未知来源不能冒充验证过的需求。',schema(QUESTION_FIELDS,['account_id','question','context','source_type']),False),
 ('update_question','编辑或搁置指定账号的问题，保留既有来源关系。',schema({'id':S,**QUESTION_FIELDS},['id','account_id']),False),
 ('create_batch','从已有真实问题建立12篇可编辑框架，问题不足时留空；没有调用AI模型。',schema({'account_id':S,'name':S,'question_ids':STRING_ARRAY},['account_id']),False),
 ('update_plan_item','为计划补写标题、材料、读者行动、观察目标和正文；不编造案例或亲历。',schema(ITEM_FIELDS,['id','account_id']),False),
 ('create_plan_draft','将已有标题正文和素材转为指定账号的本地草稿，重复操作复用草稿，不自动发布。',schema({'id':S,'account_id':S},['id','account_id']),False),
 ('observe_plan_item','记录用户提供的发布情况、指标、制作耗时和追问；空值保持未知，人工记录不是平台回执。',schema(OBSERVATION_FIELDS,['id','account_id','post_url','published_at','observed_at']),False),
 ('review_batch','读取每组4篇的观察记录与口径，显示观察时长，不以不同窗口或曝光冒充阅读进行排名。',schema({'batch_id':S,'account_id':S,'group':{'type':'integer','minimum':1,'maximum':3}},['batch_id','account_id','group']),True),
 ('promote_feedback','把真实记录的读者追问、下一篇回答和所需材料送回问题库，保留来源且不重复创建。',schema({'observation_id':S,'account_id':S},['observation_id','account_id']),False),
 ('export_content_plan','导出指定账号的定位、问题来源、内容计划和观察记录；仅本地JSON交接。',schema({'batch_id':S,'account_id':S},['batch_id','account_id']),True),
]
TOOLS=[
 ('list_media','列出本地素材与真实传输状态。加入本地不等于上传，上传不等于发布。',schema({}),True),
 ('register_media','将绝对路径的本机素材加入素材库，只引用原文件，不复制、不外传。',schema({'paths':{'type':'array','items':S,'minItems':1,'maxItems':100}},['paths']),False),
 ('get_overview','读取平台摘要、数据来源、连接状态。真实与演示数据严格分开。',schema({'dataset':DATASET,'account_id':S}),True),
 ('list_accounts','列出多平台多账号档案、品牌分组及授权状态。',schema({}),True),
 ('get_content_metrics','读取最新内容快照。支持账号筛选与条数限制；不推断日增量。',schema({'dataset':DATASET,'account_id':S,'limit':{'type':'integer','minimum':1,'maximum':100}}),True),
 ('analyze_metrics','按平台分析已导入数据，返回每条观察的证据和限制。规则分析，不调用模型。',schema({'dataset':DATASET,'account_id':S,'platform_id':S}),True),
 ('create_account','创建本地账号档案，不代表已完成第三方授权。',schema({'platform':S,'name':S,'handle':S,'brand':S,'notes':S},['platform','name','handle']),False),
 ('create_draft','为选定账号创建本地内容草稿，可按平台保存独立正文。不向外部平台发送。',schema({'title':S,'body':S,'platform_variants':PLATFORM_VARIANTS,'platforms':{'type':'array','items':S},'account_ids':{'type':'array','items':S},'media_ids':{'type':'array','items':S},'scheduled_at':S},['title','body']),False),
 ('update_draft','编辑本地草稿或进入审核。更改已批准的平台正文会退回 review，不能同时改稿并批准。',schema({'id':S,'title':S,'body':S,'platform_variants':PLATFORM_VARIANTS,'platforms':{'type':'array','items':S},'account_ids':{'type':'array','items':S},'media_ids':{'type':'array','items':S},'scheduled_at':S,'status':{'type':'string','enum':['draft','review','approved']}},['id']),False),
 ('import_metrics_csv','导入真实 CSV，保留来源及观察时间，按账号与作品去重。',schema({'kind':{'type':'string','enum':['social','ads']},'csv_text':S,'filename':S},['kind','csv_text']),False),
 ('export_drafts','导出包含目标账号与状态的草稿发布交接包。没有发布副作用。',schema({}),True),
 ('get_product_research','读取本次产品选型与官方证据来源。',schema({}),True),
]+PLANNING_TOOLS

def call(name,args):
 if name=='export_content_plan': return planning.export_plan(args.get('batch_id'),args.get('account_id'))
 if name in {t[0] for t in PLANNING_TOOLS}: return planning.dispatch(name,args)
 if name=='list_media': return media_uploads.snapshot()
 if name=='register_media': return media_uploads.register_files(args.get('paths'))
 if name=='get_overview':
  s=core.state(args.get('dataset','real'),args.get('account_id'));return {k:s[k] for k in ['dataset','accounts','summary','connectors','updated_at','remote_publishing_enabled']}
 if name=='list_accounts': return {'accounts':core.state()['accounts']}
 if name=='get_content_metrics':
  s=core.state(args.get('dataset','real'),args.get('account_id'));limit=args.get('limit',50)
  if not isinstance(limit,int) or not 1<=limit<=100: raise core.ValidationError('limit 必须为 1–100')
  return {'dataset':s['dataset'],'posts':s['posts'][:limit],'ads':s['ads'][:limit],'total_posts':len(s['posts']),'total_ads':len(s['ads'])}
 mappings={'analyze_metrics':'analyze','import_metrics_csv':'import_metrics','get_product_research':'research'}
 return core.dispatch(mappings.get(name,name),args)

def handle(m):
 ident=m.get('id');method=m.get('method');params=m.get('params',{})
 if ident is None: return None
 def ok(r):return {'jsonrpc':'2.0','id':ident,'result':r}
 if method=='initialize':return ok({'protocolVersion':params.get('protocolVersion','2024-11-05'),'capabilities':{'tools':{}},'serverInfo':{'name':'media-workspace','version':'1.0.0'},'instructions':'本地 SPT 发布与运营工作台。所有发布计划均为本地状态，不能声称已向社交平台发布。数据默认真实，演示必须明确标注。'})
 if method=='ping':return ok({})
 if method=='tools/list':return ok({'tools':[{'name':n,'description':d,'inputSchema':s,'annotations':{'readOnlyHint':read,'destructiveHint':False,'openWorldHint':False}} for n,d,s,read in TOOLS]})
 if method in ['resources/list','prompts/list']:return ok({'resources' if method=='resources/list' else 'prompts':[]})
 if method=='tools/call':
  try:
   spec=next((t for t in TOOLS if t[0]==params.get('name')),None)
   if not spec:raise core.ValidationError('未知工具')
   args=params.get('arguments',{})
   if not isinstance(args,dict):raise core.ValidationError('arguments 必须是对象')
   if set(args)-set(spec[2]['properties']):raise core.ValidationError('存在未声明参数')
   if any(k not in args for k in spec[2]['required']):raise core.ValidationError('缺少必填参数')
   result=call(spec[0],args)
   return ok({'content':[{'type':'text','text':json.dumps(result,ensure_ascii=False)}],'structuredContent':result,'isError':False})
  except (ValueError,KeyError,TypeError) as e:return ok({'content':[{'type':'text','text':str(e)}],'isError':True})
 return {'jsonrpc':'2.0','id':ident,'error':{'code':-32601,'message':'Method not found'}}

def main():
 for line in sys.stdin:
  try:
   if len(line)>6_000_000:raise ValueError('request too large')
   result=handle(json.loads(line))
  except (ValueError,TypeError,AttributeError):result={'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Invalid JSON-RPC message'}}
  except Exception as e:
   print(type(e).__name__,file=sys.stderr);result={'jsonrpc':'2.0','id':None,'error':{'code':-32603,'message':'Local operation failed'}}
  if result: print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
