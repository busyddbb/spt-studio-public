"""Markdown metadata and note history have the same meaning on Windows and Mac."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ..clients import rewrite, save_clients
from ..library import document_item, split_frontmatter
from ..notes import Notes, parse
from ..parsing import headings


class NewlineTests(unittest.TestCase):
    def test_frontmatter_accepts_windows_and_legacy_editor_lines(self):
        for newline in ('\n', '\r\n', '\r'):
            with self.subTest(newline=repr(newline)):
                text=newline.join(('\ufeff---','标题: 示例标题','标签: [角色, 参考]','工具: Example Tool','说明: 主参考脸','---','# 正文','段落。',''))
                values, body=split_frontmatter(text)
                self.assertEqual(values,{'标题':'示例标题','标签':['角色','参考'],'工具':'Example Tool','说明':'主参考脸'})
                self.assertEqual(body,'# 正文\n段落。\n')

    def test_binary_read_of_windows_documents_keeps_metadata_out_of_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            path=root/'提示词.md'
            path.write_bytes('---\r\n标题: 示例标题\r\n标签: [角色, 参考]\r\n工具: Example Tool\r\n说明: 主参考脸\r\n---\r\n# 示例标题\r\n提示词正文\r\n'.encode('utf-8'))
            item=document_item(path,root,'prompt','示例',None)
            self.assertEqual((item.title,item.tags,item.tool,item.note),('示例标题','角色, 参考','Example Tool','主参考脸'))
            self.assertEqual(item.body,'# 示例标题\n提示词正文')
            self.assertEqual(item.text,'提示词正文')

    def test_headings_and_notes_accept_crlf_without_leaking_control_characters(self):
        self.assertEqual(headings('# 当前采用\r\n正文\r\n# 旧版\r\n历史\r\n',1),[('当前采用','\n正文\n'),('旧版','\n历史\n')])
        self.assertEqual(parse('\ufeff---\r\n颜色: sky\r\n日期: 2026-10-28\r\n---\r\n实际标题\r\n正文\r\n'),('sky','2026-10-28','实际标题\n正文'))

    def test_client_rewrite_keeps_surrounding_words_with_logical_line_endings(self):
        text='# 客户说明\r\n\r\n开头。\r\n\r\n| 简称 | 名字 |\r\n|---|---|\r\n| 示例 | 旧名 |\r\n\r\n末尾。\r\n'
        table='| 简称 | 名字 |\n|---|---|\n| 示例 | 新名 |\n'
        self.assertEqual(rewrite(text,table),'# 客户说明\n\n开头。\n\n'+table+'\n末尾。\n')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            path=root/'客户.md'
            path.write_bytes(text.encode('utf-8'))
            save_clients(root,[{'name':'自己','clients':[{'code':'示例','name':'新名'}]}],{})
            saved=path.read_text(encoding='utf-8')
            self.assertTrue(saved.startswith('# 客户说明\n\n开头。\n\n| 简称 |'))
            self.assertTrue(saved.endswith('\n末尾。\n'))
            self.assertNotIn(b'\r\r\n',path.read_bytes())


class TakenDownTimeTests(unittest.TestCase):
    def test_action_order_survives_restart_without_changing_note_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            notes=Notes(root)
            old,new='20261001-090000-aaaa','20261020-090000-bbbb'
            originals={}
            for identifier in (old,new):
                path=root/'便签/随手记'/f'{identifier}.md'
                path.parent.mkdir(parents=True,exist_ok=True)
                raw=f'---\r\n颜色: sky\r\n---\r\n{identifier}\r\n'.encode()
                path.write_bytes(raw)
                originals[identifier]=(raw,path.stat().st_mtime_ns)
            # Equal clock ticks must still reflect action order, not note IDs
            # or NTFS ctime (which is the file creation time).
            moment=dt.datetime(2026,10,28,12,tzinfo=dt.timezone.utc)
            with patch('spt.server.notes.now',return_value=moment):
                notes.take_down({'rope':'随手记','id':new})
                notes.take_down({'rope':'随手记','id':old})
            restarted=Notes(root)
            self.assertEqual([item['id'] for item in restarted.shelf()],[old,new])
            for identifier,(raw,mtime) in originals.items():
                path=root/'便签/.已撤下/随手记'/f'{identifier}.md'
                self.assertEqual(path.read_bytes(),raw)
                self.assertEqual(path.stat().st_mtime_ns,mtime)
            restarted.restore({'rope':'随手记','id':old})
            self.assertNotIn('随手记/'+old,restarted.layout()['taken_down'])


if __name__=='__main__':unittest.main()
