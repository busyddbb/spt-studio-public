"""JSON-in/JSON-out automation entry; no server required."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
import core, media_uploads, planning
PLANNING_ACTIONS=['planning_workspace','save_strategy','add_question','update_question','create_batch','update_plan_item','create_plan_draft','observe_plan_item','review_batch','promote_feedback','export_content_plan']
p=argparse.ArgumentParser(description='SPT 发布与运营：所有操作返回 JSON，不会实际发布内容。')
p.add_argument('action',choices=['state','research','analyze','create_account','update_account','create_draft','update_draft','import_metrics','export_drafts','list_media','register_media','media_action']+PLANNING_ACTIONS)
p.add_argument('--input-file',help='JSON 参数文件；使用 - 从 stdin 读取')
p.add_argument('--dataset',choices=['real','demo'],default='real')
p.add_argument('--account-id')
p.add_argument('--csv-file');p.add_argument('--kind',choices=['social','ads'])
a=p.parse_args()
try:
 data=json.loads(sys.stdin.read() if a.input_file=='-' else Path(a.input_file).read_text(encoding='utf-8')) if a.input_file else {}
 if a.action in ['state','analyze']: data.update(dataset=a.dataset,account_id=a.account_id)
 if a.csv_file: data.update(csv_text=Path(a.csv_file).read_text(encoding='utf-8-sig'),kind=a.kind,filename=Path(a.csv_file).name)
 if not isinstance(data,dict): raise core.ValidationError('参数文件必须为 JSON 对象')
 if a.action in PLANNING_ACTIONS and a.account_id: data['account_id']=a.account_id
 if a.action=='export_content_plan': result=planning.export_plan(data.get('batch_id'),data.get('account_id'))
 elif a.action in PLANNING_ACTIONS: result=planning.dispatch(a.action,data)
 elif a.action=='list_media': result=media_uploads.snapshot()
 elif a.action=='register_media': result=media_uploads.register_files(data.get('paths'))
 elif a.action=='media_action': result=media_uploads.job_action(data.get('id'),data.get('action'))
 else: result=core.dispatch(a.action,data)
 print(json.dumps(result,ensure_ascii=False,indent=2))
except (core.ValidationError,ValueError,KeyError,TypeError,OSError) as e:
 print(json.dumps({'error':str(e)},ensure_ascii=False));sys.exit(1)
